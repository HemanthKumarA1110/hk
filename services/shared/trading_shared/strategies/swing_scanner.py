"""Swing scan using Angel One daily historical candles for Nifty 50."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import redis
from sqlalchemy.orm import Session

from trading_shared.backtest.data_loader import BacktestDataLoader
from trading_shared.broker.angel_one.exceptions import AngelOneAuthError
from trading_shared.config import get_settings
from trading_shared.market.redis_bus import MarketRedisBus
from trading_shared.market.scrip_master import ScripMasterService
from trading_shared.strategies.data_provider import StrategyDataProvider
from trading_shared.strategies.orchestrator import REDIS_SWING_KEY
from trading_shared.strategies.swing_engine import SwingEngine
from trading_shared.strategies.types import StrategySignalCandidate

logger = logging.getLogger(__name__)

REDIS_SWING_PICKS_KEY = "strategy:swing:picks"
REDIS_SWING_PICKS_TTL = 3600


class AngelOneSwingDataProvider(StrategyDataProvider):
    """Strategy data provider backed by Angel One daily OHLCV."""

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
        self.loader = BacktestDataLoader(db)
        self._frame_cache: dict[str, pd.DataFrame] = {}
        self.data_sources: dict[str, str] = {}

    def build_daily_frame(self, token: str, symbol: str, days: int = 120) -> pd.DataFrame:
        cache_key = f"{token}:{days}"
        if cache_key in self._frame_cache:
            return self._frame_cache[cache_key]

        to_date = datetime.now(timezone.utc).date()
        from_date = to_date - timedelta(days=max(days + 90, 220))
        df, source = self.loader.load(
            self.user_id,
            symbol,
            token,
            "NSE",
            "1d",
            from_date.isoformat(),
            to_date.isoformat(),
        )
        self.data_sources[symbol] = source

        if source == "demo" or len(df) < 30:
            if source == "demo":
                logger.warning("Angel One history unavailable for %s; skipping demo fallback", symbol)
            else:
                logger.warning("Insufficient Angel One history for %s (%s bars); skipping", symbol, len(df))
            df = pd.DataFrame(columns=["open", "high", "low", "close", "volume", "symbol"])
            self._frame_cache[cache_key] = df
            return df

        if "timestamp" in df.columns:
            df = df.sort_values("timestamp")
        df = df.tail(days + 30).reset_index(drop=True)
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
        df["symbol"] = symbol

        self._frame_cache[cache_key] = df
        return df


def run_swing_scan(db: Session, user_id: int, limit: int = 10) -> dict[str, object]:
    settings = get_settings()
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    scrip = ScripMasterService(redis_client)
    if not scrip.ensure_loaded():
        raise AngelOneAuthError("Scrip master not loaded. Connect broker and retry.")

    provider = AngelOneSwingDataProvider(
        MarketRedisBus(settings.REDIS_URL),
        scrip,
        db,
        user_id,
    )
    universe = provider.nifty_universe()
    if not universe:
        raise AngelOneAuthError("Nifty 50 universe unavailable from scrip master.")

    engine = SwingEngine(provider)
    signals: list[StrategySignalCandidate] = engine.evaluate(limit=limit)
    generated_at = datetime.now(timezone.utc).isoformat()
    signal_dicts = [signal.to_dict() for signal in signals]

    angel_count = sum(1 for source in provider.data_sources.values() if source == "angel_one")
    payload = {
        "generated_at": generated_at,
        "source": "angel_one" if angel_count else "mixed",
        "universe_size": len(universe),
        "history_loaded": angel_count,
        "signals": signal_dicts,
    }

    redis_client.setex(REDIS_SWING_PICKS_KEY, REDIS_SWING_PICKS_TTL, json.dumps(payload))
    redis_client.setex(
        REDIS_SWING_KEY,
        300,
        json.dumps({"generated_at": generated_at, "signals": signal_dicts}),
    )
    logger.info(
        "Swing scan complete user_id=%s universe=%s picks=%s angel_history=%s",
        user_id,
        len(universe),
        len(signal_dicts),
        angel_count,
    )
    return payload


def get_swing_picks() -> dict[str, object]:
    settings = get_settings()
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    raw = redis_client.get(REDIS_SWING_PICKS_KEY)
    desk = json.loads(raw) if raw else None

    from trading_shared.strategies.orchestrator import StrategyOrchestrator
    from trading_shared.strategies.signal_cache import pick_fresher_signal_payload

    cached = StrategyOrchestrator.get_cached("swing")
    merged = pick_fresher_signal_payload(desk, cached, fallback_source="orchestrator")
    return {
        "generated_at": merged.get("generated_at"),
        "source": merged.get("source", "cache"),
        "universe_size": merged.get("universe_size"),
        "history_loaded": merged.get("history_loaded"),
        "signals": merged.get("signals", []),
    }
