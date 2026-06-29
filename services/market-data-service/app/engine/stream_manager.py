"""Central live stream orchestrator for Angel One SmartAPI."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import redis
from sqlalchemy.orm import Session

from trading_shared.broker.angel_one.session_manager import AngelOneSessionManager
from trading_shared.config import get_settings
from trading_shared.db.session import SessionLocal
from trading_shared.market.analytics import black_scholes_greeks, compute_pcr, parse_tick
from trading_shared.market.scrip_master import REDIS_SCRIP_UPDATED_KEY
from trading_shared.market.scrip_master import ScripMasterService
from trading_shared.market.websocket_stream import AngelOneWebSocketStream
from trading_shared.models import MarketCandle, OptionChainSnapshot

from trading_shared.market.redis_bus import MarketRedisBus
from trading_shared.market.scanner import MarketScanner
from app.engine.candle_builder import CandleBuilder

logger = logging.getLogger(__name__)


class StreamManager:
    _instance: "StreamManager | None" = None

    def __init__(self):
        settings = get_settings()
        self.settings = settings
        self.redis_bus = MarketRedisBus(settings.REDIS_URL)
        self.redis_raw = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.scrip_service = ScripMasterService(self.redis_raw)
        self.candle_builder = CandleBuilder()
        self.scanner = MarketScanner(self.redis_bus, self.scrip_service)
        self.stream: AngelOneWebSocketStream | None = None
        self.ticks_received = 0
        self.last_tick_at: datetime | None = None
        self.scanner_task: asyncio.Task | None = None
        self._token_symbol_map: dict[str, str] = {}
        self._running = False

    @classmethod
    def get(cls) -> "StreamManager":
        if cls._instance is None:
            cls._instance = StreamManager()
        return cls._instance

    async def start(self) -> dict[str, Any]:
        if self._running:
            return self.status()

        await self.scrip_service.refresh()
        session = self._load_system_session()
        if not session:
            logger.warning("Market stream not started: no Angel One session in Redis")
            self.redis_bus.store_stream_status(self.status())
            return self.status()

        nse_cm_tokens, nse_fo_tokens, self._token_symbol_map = self._build_subscription_universe()
        token_groups = AngelOneWebSocketStream.build_token_groups(nse_cm_tokens, nse_fo_tokens)

        self.stream = AngelOneWebSocketStream(
            auth_token=session["jwt_token"],
            api_key=session.get("api_key") or self.settings.ANGEL_API_KEY,
            client_code=session["client_code"],
            feed_token=session.get("feed_token") or "",
            on_tick=self._handle_tick,
        )
        self.stream.set_subscriptions(token_groups)
        self.stream.start()
        self._running = True
        self.scanner_task = asyncio.create_task(self._scanner_loop())
        status = self.status()
        self.redis_bus.store_stream_status(status)
        logger.info("Market stream started with %s CM and %s FO tokens", len(nse_cm_tokens), len(nse_fo_tokens))
        return status

    async def stop(self) -> dict[str, Any]:
        self._running = False
        if self.scanner_task:
            self.scanner_task.cancel()
        if self.stream:
            self.stream.stop()
        status = self.status()
        self.redis_bus.store_stream_status(status)
        return status

    def status(self) -> dict[str, Any]:
        subscriptions = 0
        if self.stream and self.stream._subscriptions:
            for group in self.stream._subscriptions:
                subscriptions += len(group.get("tokens", []))
        return {
            "connected": bool(self.stream and self.stream.connected),
            "subscriptions": subscriptions,
            "ticks_received": self.ticks_received,
            "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
            "scanner_running": self._running,
            "scrip_master_updated_at": self.redis_raw.get(REDIS_SCRIP_UPDATED_KEY),
        }

    def _load_system_session(self) -> dict[str, Any] | None:
        blob = self.redis_raw.get("angel_one:system:session")
        if blob:
            payload = json.loads(blob)
            payload["api_key"] = self.settings.ANGEL_API_KEY
            return payload

        db = SessionLocal()
        try:
            from trading_shared.models import BrokerSession

            session = (
                db.query(BrokerSession)
                .filter(BrokerSession.is_active.is_(True))
                .order_by(BrokerSession.created_at.desc())
                .first()
            )
            if not session:
                return None
            return {
                "jwt_token": session.jwt_token,
                "refresh_token": session.refresh_token,
                "feed_token": session.feed_token,
                "client_code": session.client_code,
                "api_key": self.settings.ANGEL_API_KEY,
            }
        finally:
            db.close()

    def _build_subscription_universe(self) -> tuple[list[str], list[str], dict[str, str]]:
        token_symbol: dict[str, str] = {}
        nse_cm: list[str] = []
        nse_fo: list[str] = []

        for index in ("NIFTY", "BANKNIFTY"):
            inst = self.scrip_service.index_token(index)
            if inst:
                nse_cm.append(inst.token)
                token_symbol[inst.token] = index

        for inst in self.scrip_service.nifty50_equities():
            nse_cm.append(inst.token)
            token_symbol[inst.token] = inst.symbol

        nifty_inst = self.scrip_service.index_token("NIFTY")
        bank_inst = self.scrip_service.index_token("BANKNIFTY")
        nifty_spot = 24000.0
        bank_spot = 52000.0
        if nifty_inst:
            tick = self.redis_bus.get_tick(1, nifty_inst.token)
            if tick:
                nifty_spot = tick.get("ltp", nifty_spot)
        if bank_inst:
            tick = self.redis_bus.get_tick(1, bank_inst.token)
            if tick:
                bank_spot = tick.get("ltp", bank_spot)

        for underlying, spot in (("NIFTY", nifty_spot), ("BANKNIFTY", bank_spot)):
            for inst in self.scrip_service.nearest_expiry_options(underlying, spot, strike_window=8):
                nse_fo.append(inst.token)
                token_symbol[inst.token] = inst.symbol
            for inst in self.scrip_service.futures_chain(underlying, count=2):
                nse_fo.append(inst.token)
                token_symbol[inst.token] = inst.symbol

        # Angel One allows max 50 tokens per subscription batch; trim if needed
        nse_cm = list(dict.fromkeys(nse_cm))[:40]
        nse_fo = list(dict.fromkeys(nse_fo))[:40]
        return nse_cm, nse_fo, token_symbol

    def _handle_tick(self, raw: dict[str, Any]) -> None:
        tick = parse_tick(raw)
        token = tick["token"]
        symbol = self._token_symbol_map.get(token)
        if not symbol:
            inst = self.scrip_service.get_by_token(token)
            symbol = inst.symbol if inst else token
            self._token_symbol_map[token] = symbol
        tick["symbol"] = symbol

        exchange_type = tick.get("exchange_type", 1)
        self.redis_bus.store_tick(exchange_type, token, tick)
        self.redis_bus.publish_tick(tick)

        completed = self.candle_builder.ingest(token, symbol, tick["ltp"], tick.get("volume", 0))
        for candle in completed:
            self.redis_bus.store_candle(token, candle["interval"], candle)
            self._persist_candle(candle)

        self.ticks_received += 1
        self.last_tick_at = datetime.now(timezone.utc)
        if self.ticks_received % 100 == 0:
            self.redis_bus.store_stream_status(self.status())

        if symbol.endswith("CE") or symbol.endswith("PE") or "FUT" in symbol:
            self._update_option_chain_snapshot(symbol, tick)

    def _persist_candle(self, candle: dict[str, Any]) -> None:
        db = SessionLocal()
        try:
            db.add(
                MarketCandle(
                    token=candle["token"],
                    symbol=candle["symbol"],
                    exchange="NSE",
                    interval=candle["interval"],
                    candle_ts=datetime.fromisoformat(candle["candle_ts"]),
                    open=candle["open"],
                    high=candle["high"],
                    low=candle["low"],
                    close=candle["close"],
                    volume=candle["volume"],
                    vwap=candle.get("vwap"),
                )
            )
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def _update_option_chain_snapshot(self, symbol: str, tick: dict[str, Any]) -> None:
        underlying = "NIFTY" if "NIFTY" in symbol and "BANKNIFTY" not in symbol else "BANKNIFTY"
        chain = self.redis_bus.get_option_chain(underlying) or {
            "underlying": underlying,
            "expiry": "",
            "spot": 0,
            "rows": {},
            "total_ce_oi": 0,
            "total_pe_oi": 0,
        }
        rows = chain.setdefault("rows", {})
        rows[symbol] = {
            "symbol": symbol,
            "token": tick["token"],
            "ltp": tick["ltp"],
            "oi": tick.get("oi", 0),
            "volume": tick.get("volume", 0),
        }
        total_ce_oi = sum(row["oi"] for key, row in rows.items() if key.endswith("CE"))
        total_pe_oi = sum(row["oi"] for key, row in rows.items() if key.endswith("PE"))
        chain["total_ce_oi"] = total_ce_oi
        chain["total_pe_oi"] = total_pe_oi
        chain["pcr"] = compute_pcr(total_ce_oi, total_pe_oi)
        self.redis_bus.store_option_chain(underlying, chain)

    async def _scanner_loop(self) -> None:
        while self._running:
            try:
                db = SessionLocal()
                try:
                    self.scanner.run_scan(db)
                    await self._build_option_chain_metrics()
                finally:
                    db.close()
            except Exception:
                logger.exception("Scanner loop failed")
            await asyncio.sleep(30)

    async def _build_option_chain_metrics(self) -> None:
        for underlying in ("NIFTY", "BANKNIFTY"):
            chain = self.redis_bus.get_option_chain(underlying)
            if not chain:
                continue
            index_inst = self.scrip_service.index_token(underlying)
            spot = 0.0
            if index_inst:
                tick = self.redis_bus.get_tick(1, index_inst.token)
                spot = tick.get("ltp", 0) if tick else 0
            rows = []
            for symbol, row in chain.get("rows", {}).items():
                strike = self._extract_strike(symbol)
                opt_type = "CE" if symbol.endswith("CE") else "PE"
                iv = 0.18
                greeks = black_scholes_greeks(spot, strike, 7 / 365, 0.07, iv, opt_type)
                rows.append(
                    {
                        **row,
                        "strike": strike,
                        "option_type": opt_type,
                        "iv": greeks.iv,
                        "delta": greeks.delta,
                        "gamma": greeks.gamma,
                        "theta": greeks.theta,
                        "vega": greeks.vega,
                    }
                )
            payload = {
                "underlying": underlying,
                "expiry": chain.get("expiry", ""),
                "spot": spot,
                "pcr": chain.get("pcr"),
                "total_ce_oi": chain.get("total_ce_oi", 0),
                "total_pe_oi": chain.get("total_pe_oi", 0),
                "rows": rows,
            }
            self.redis_bus.store_option_chain(underlying, payload)
            db = SessionLocal()
            try:
                db.add(
                    OptionChainSnapshot(
                        underlying=underlying,
                        expiry=chain.get("expiry", ""),
                        pcr=chain.get("pcr"),
                        total_ce_oi=chain.get("total_ce_oi", 0),
                        total_pe_oi=chain.get("total_pe_oi", 0),
                        payload=json.dumps(payload),
                    )
                )
                db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()

    @staticmethod
    def _extract_strike(symbol: str) -> float:
        digits = "".join(ch if ch.isdigit() else " " for ch in symbol).split()
        if not digits:
            return 0.0
        return float(digits[-1])

    async def fetch_historical_candles(
        self,
        db: Session,
        user_id: int,
        exchange: str,
        symboltoken: str,
        interval: str,
        fromdate: str,
        todate: str,
    ) -> dict[str, Any]:
        from trading_shared.broker.angel_one.schemas import CandleRequest
        from trading_shared.broker.angel_one.session_manager import AngelOneSessionManager

        manager = AngelOneSessionManager(db, self.redis_raw)
        client = await manager.get_client_for_user(user_id)
        api_interval = {
            "1m": "ONE_MINUTE",
            "3m": "THREE_MINUTE",
            "5m": "FIVE_MINUTE",
            "15m": "FIFTEEN_MINUTE",
            "1d": "ONE_DAY",
        }.get(interval, "ONE_MINUTE")
        return await client.get_candles(
            CandleRequest(
                exchange=exchange,
                symboltoken=symboltoken,
                interval=api_interval,
                fromdate=fromdate,
                todate=todate,
            )
        )
