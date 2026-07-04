"""On-demand intraday scan using live market data and IntradayEngine."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import redis
from sqlalchemy.orm import Session

from trading_shared.backtest.data_loader import INTERVAL_MAP, BacktestDataLoader
from trading_shared.broker.angel_one.exceptions import AngelOneAuthError
from trading_shared.broker.angel_one.schemas import CandleRequest, LTPRequest
from trading_shared.broker.angel_one.session_manager import AngelOneSessionManager
from trading_shared.config import get_settings
from trading_shared.market.index_quotes import extract_ltp_from_response
from trading_shared.market.redis_bus import MarketRedisBus
from trading_shared.market.scanner import MarketScanner
from trading_shared.market.scrip_master import Instrument, ScripMasterService
from trading_shared.strategies.data_provider import StrategyDataProvider
from trading_shared.strategies.intraday_engine import IntradayEngine
from trading_shared.strategies.orchestrator import REDIS_INTRADAY_KEY
from trading_shared.strategies.scoring import INTRADAY_MIN_SCORE, rank_top
from trading_shared.strategies.types import Confirmation, EngineType, SignalSide, StrategySignalCandidate

logger = logging.getLogger(__name__)

REDIS_INTRADAY_PICKS_KEY = "strategy:intraday:picks"
REDIS_INTRADAY_PICKS_TTL = 300
SCAN_HIT_MIN_SCORE = 10.0
CANDLE_MIN_BARS = 10


class AngelOneIntradayDataProvider(StrategyDataProvider):
    """Hydrate Redis ticks and intraday frames from Angel One when the websocket cache is empty."""

    def __init__(
        self,
        redis_bus: MarketRedisBus,
        scrip_service: ScripMasterService,
        db: Session,
        user_id: int,
    ):
        super().__init__(redis_bus, scrip_service)
        self.db = db
        self.user_id = user_id
        self._frame_cache: dict[str, pd.DataFrame] = {}
        self.quotes_bootstrapped = 0
        self.candles_loaded = 0
        self._client = None

    async def prepare(self) -> None:
        redis_client = redis.from_url(get_settings().REDIS_URL, decode_responses=True)
        manager = AngelOneSessionManager(self.db, redis_client)
        self._client = await manager.get_client_for_user(self.user_id)

        equities = self.scrip_service.nifty50_equities()
        sem = asyncio.Semaphore(6)

        async def quote_one(inst: Instrument) -> None:
            if self.redis_bus.get_tick(1, inst.token):
                self.quotes_bootstrapped += 1
                return
            async with sem:
                try:
                    response = await self._client.get_ltp(
                        LTPRequest(
                            exchange="NSE",
                            tradingsymbol=inst.symbol,
                            symboltoken=inst.token,
                        )
                    )
                    tick = _tick_from_ltp_response(inst, response)
                    if tick:
                        self.redis_bus.store_tick(1, inst.token, tick)
                        self.quotes_bootstrapped += 1
                except Exception:
                    logger.debug("LTP bootstrap failed for %s", inst.symbol)

        await asyncio.gather(*[quote_one(inst) for inst in equities])

        async def candles_one(inst: Instrument) -> None:
            cache_key = f"{inst.token}:40"
            if cache_key in self._frame_cache:
                return
            async with sem:
                df = await self._fetch_candles(inst)
                if len(df) >= CANDLE_MIN_BARS:
                    self._frame_cache[cache_key] = df
                    self.candles_loaded += 1
                await asyncio.sleep(0.15)

        await asyncio.gather(*[candles_one(inst) for inst in equities])

    async def _fetch_candles(self, inst: Instrument) -> pd.DataFrame:
        db_df = self._load_from_db(inst.token, "5m")
        if len(db_df) >= CANDLE_MIN_BARS:
            return db_df.tail(60).reset_index(drop=True)

        today = date.today()
        from_date = (today - timedelta(days=7)).isoformat()
        to_date = today.isoformat()
        try:
            response = await self._client.get_candles(
                CandleRequest(
                    exchange="NSE",
                    symboltoken=inst.token,
                    interval=INTERVAL_MAP.get("5m", "FIVE_MINUTE"),
                    fromdate=f"{from_date} 09:15",
                    todate=f"{to_date} 15:30",
                )
            )
            df = _parse_candle_response(response, inst.symbol)
            if len(df) >= CANDLE_MIN_BARS:
                return df.tail(60).reset_index(drop=True)
        except Exception:
            logger.debug("Angel One 5m candle fetch failed for %s", inst.symbol)
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    def _load_from_db(self, token: str, interval: str) -> pd.DataFrame:
        from trading_shared.models import MarketCandle

        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)
        rows = (
            self.db.query(MarketCandle)
            .filter(
                MarketCandle.token == token,
                MarketCandle.interval == interval,
                MarketCandle.candle_ts >= start,
            )
            .order_by(MarketCandle.candle_ts.asc())
            .all()
        )
        if not rows:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        return pd.DataFrame(
            [
                {
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                }
                for r in rows
            ]
        )

    def _load_candles(self, token: str, symbol: str) -> pd.DataFrame:
        loader = BacktestDataLoader(self.db)
        today = date.today()
        from_date = (today - timedelta(days=7)).isoformat()
        to_date = today.isoformat()
        try:
            df, source = loader.load(
                self.user_id,
                symbol,
                token,
                "NSE",
                "5m",
                from_date,
                to_date,
                use_demo_data=False,
            )
            if source == "demo" or df.empty:
                return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            out = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
            out["symbol"] = symbol
            return out.tail(60).reset_index(drop=True)
        except Exception:
            logger.debug("Intraday candle load failed for %s", symbol)
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    def build_intraday_frame(self, token: str, symbol: str, bars: int = 60) -> pd.DataFrame:
        cache_key = f"{token}:{bars}"
        if cache_key in self._frame_cache:
            return self._frame_cache[cache_key]

        df = super().build_intraday_frame(token, symbol, bars=bars)
        if len(df) >= 10:
            self._frame_cache[cache_key] = df
            return df

        loaded = self._frame_cache.get(f"{token}:40")
        if loaded is not None and len(loaded) >= CANDLE_MIN_BARS:
            self._frame_cache[cache_key] = loaded
            return loaded
        return df


def _parse_candle_response(response: dict, symbol: str) -> pd.DataFrame:
    candles = response.get("data") or []
    records = []
    for row in candles:
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            continue
        records.append(
            {
                "timestamp": pd.to_datetime(row[0], format="mixed", errors="coerce"),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        )
    if not records:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(records)
    df["symbol"] = symbol
    return df


def _signals_from_scan_hits(
    scan_hits: list[dict],
    provider: AngelOneIntradayDataProvider,
    limit: int,
    exclude: set[str] | None = None,
) -> list[StrategySignalCandidate]:
    """Build desk picks from live scanner hits when TA scoring finds nothing."""
    exclude = exclude or set()
    best_by_symbol: dict[str, dict] = {}
    for hit in sorted(scan_hits, key=lambda item: float(item.get("score") or 0), reverse=True):
        symbol = hit.get("symbol")
        if not symbol or symbol in exclude or symbol in best_by_symbol:
            continue
        if float(hit.get("score") or 0) < SCAN_HIT_MIN_SCORE:
            continue
        best_by_symbol[symbol] = hit

    candidates: list[StrategySignalCandidate] = []
    for hit in list(best_by_symbol.values())[:limit]:
        symbol = hit["symbol"]
        token = str(hit["token"])
        tick = provider.tick(token) or {}
        details = hit.get("details") or {}
        ltp = float(tick.get("ltp") or details.get("ltp") or 0)
        if ltp <= 0:
            continue

        scan_type = str(hit.get("scan_type") or "momentum")
        side = SignalSide.SELL if scan_type == "gap_down" else SignalSide.BUY
        day_low = float(tick.get("low") or ltp * 0.995)
        day_high = float(tick.get("high") or ltp * 1.005)
        if side == SignalSide.BUY:
            stoploss = round(day_low, 2)
            target = round(ltp + 2 * max(ltp - day_low, ltp * 0.003), 2)
        else:
            stoploss = round(day_high, 2)
            target = round(ltp - 2 * max(day_high - ltp, ltp * 0.003), 2)

        score = float(hit.get("score") or SCAN_HIT_MIN_SCORE)
        confirmations = [
            Confirmation("scanner_hit", True, 20, scan_type),
            Confirmation("live_quote", bool(tick), 10),
            Confirmation("momentum", scan_type in {"momentum", "breakout", "relative_volume"}, 10),
            Confirmation("gap", scan_type in {"gap_up", "gap_down"}, 8),
        ]
        candidates.append(
            StrategySignalCandidate(
                engine=EngineType.INTRADAY,
                strategy_name="intraday_scanner",
                symbol=symbol,
                token=token,
                side=side,
                entry=round(ltp, 2),
                stoploss=stoploss,
                targets=[target],
                trailing_stop=stoploss,
                timeframe="5m",
                score=score,
                confidence=min(score / 100, 1.0),
                risk_reward=2.0,
                confirmations=confirmations,
                metadata={"source": "scanner_hit", "scan_type": scan_type},
            )
        )
    return candidates


class ScanIntradayEngine(IntradayEngine):
    """Scan the full Nifty 50 universe during on-demand desk scans."""

    def _build_universe(self) -> list[tuple[str, str]]:
        hits = self.data.scan_hits()
        universe: dict[str, tuple[str, str]] = {}
        for hit in hits:
            universe[hit["symbol"]] = (hit["token"], hit["symbol"])
        for token, symbol in self.data.nifty_universe():
            universe.setdefault(symbol, (token, symbol))
        return list(universe.values())


def _tick_from_ltp_response(inst: Instrument, response: dict) -> dict | None:
    ltp = extract_ltp_from_response(response, inst.token)
    if ltp is None:
        return None

    data = response.get("data") or {}
    row: dict = {}
    if isinstance(data, dict):
        if data.get("ltp") is not None:
            row = data
        else:
            candidate = data.get(str(inst.token))
            if isinstance(candidate, dict):
                row = candidate

    open_px = float(row.get("open") or ltp)
    high = float(row.get("high") or ltp)
    low = float(row.get("low") or ltp)
    close_px = float(row.get("close") or open_px)
    volume = float(row.get("volume") or row.get("tradeVolume") or 0)

    return {
        "token": inst.token,
        "symbol": inst.symbol,
        "exchange": "NSE",
        "ltp": ltp,
        "open": open_px,
        "high": high,
        "low": low,
        "close": close_px,
        "volume": volume,
    }


def run_intraday_scan(db: Session, user_id: int, limit: int = 10) -> dict[str, object]:
    settings = get_settings()
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    scrip = ScripMasterService(redis_client)
    if not scrip.ensure_loaded():
        raise AngelOneAuthError("Scrip master not loaded. Connect broker and retry.")

    bus = MarketRedisBus(settings.REDIS_URL)
    provider = AngelOneIntradayDataProvider(bus, scrip, db, user_id)

    async def execute() -> tuple[list[StrategySignalCandidate], int, list]:
        await provider.prepare()
        scan_payload = MarketScanner(bus, scrip).run_scan(db)
        scan_hits = scan_payload.get("hits") or []
        engine = ScanIntradayEngine(provider)
        signals = engine.evaluate(limit=limit)
        if len(signals) < limit and scan_hits:
            existing = {signal.symbol for signal in signals}
            fallback = _signals_from_scan_hits(
                scan_hits,
                provider,
                limit - len(signals),
                exclude=existing,
            )
            signals = rank_top(list(signals) + fallback, limit)
        return signals, provider.quotes_bootstrapped, scan_hits

    try:
        signals, quotes_bootstrapped, scan_hits = asyncio.run(execute())
    except AngelOneAuthError:
        raise
    except Exception as exc:
        logger.exception("Angel One intraday scan failed user_id=%s", user_id)
        raise AngelOneAuthError(f"Intraday scan failed: {exc}") from exc

    generated_at = datetime.now(timezone.utc).isoformat()
    signal_dicts = [signal.to_dict() for signal in signals]

    universe_symbols: set[str] = {hit["symbol"] for hit in scan_hits if hit.get("symbol")}
    for token, symbol in provider.nifty_universe():
        universe_symbols.add(symbol)

    payload = {
        "generated_at": generated_at,
        "source": "angel_one" if quotes_bootstrapped else "live",
        "universe_size": len(universe_symbols),
        "history_loaded": quotes_bootstrapped,
        "candles_loaded": provider.candles_loaded,
        "scan_hits": len(scan_hits),
        "min_score": INTRADAY_MIN_SCORE,
        "signals": signal_dicts,
    }

    redis_client.setex(REDIS_INTRADAY_PICKS_KEY, REDIS_INTRADAY_PICKS_TTL, json.dumps(payload))
    redis_client.setex(
        REDIS_INTRADAY_KEY,
        300,
        json.dumps({"generated_at": generated_at, "signals": signal_dicts}),
    )
    logger.info(
        "Intraday scan complete user_id=%s universe=%s scan_hits=%s picks=%s quotes=%s candles=%s",
        user_id,
        len(universe_symbols),
        len(scan_hits),
        len(signal_dicts),
        quotes_bootstrapped,
        provider.candles_loaded,
    )
    return payload


def get_intraday_picks() -> dict[str, object]:
    settings = get_settings()
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    raw = redis_client.get(REDIS_INTRADAY_PICKS_KEY)
    desk = json.loads(raw) if raw else None

    from trading_shared.strategies.orchestrator import StrategyOrchestrator
    from trading_shared.strategies.signal_cache import pick_fresher_signal_payload

    cached = StrategyOrchestrator.get_cached("intraday")
    merged = pick_fresher_signal_payload(desk, cached, fallback_source="orchestrator")
    return {
        "generated_at": merged.get("generated_at"),
        "source": merged.get("source", "cache"),
        "universe_size": merged.get("universe_size"),
        "history_loaded": merged.get("history_loaded"),
        "candles_loaded": merged.get("candles_loaded"),
        "scan_hits": merged.get("scan_hits"),
        "min_score": merged.get("min_score", INTRADAY_MIN_SCORE),
        "signals": merged.get("signals", []),
    }
