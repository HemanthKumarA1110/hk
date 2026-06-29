"""On-demand intraday scan using live market data and IntradayEngine."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import redis
from sqlalchemy.orm import Session

from trading_shared.broker.angel_one.exceptions import AngelOneAuthError
from trading_shared.config import get_settings
from trading_shared.market.redis_bus import MarketRedisBus
from trading_shared.market.scanner import MarketScanner
from trading_shared.market.scrip_master import ScripMasterService
from trading_shared.strategies.data_provider import StrategyDataProvider
from trading_shared.strategies.intraday_engine import IntradayEngine
from trading_shared.strategies.orchestrator import REDIS_INTRADAY_KEY
from trading_shared.strategies.scoring import INTRADAY_MIN_SCORE
from trading_shared.strategies.types import StrategySignalCandidate

logger = logging.getLogger(__name__)

REDIS_INTRADAY_PICKS_KEY = "strategy:intraday:picks"
REDIS_INTRADAY_PICKS_TTL = 300


def run_intraday_scan(db: Session, user_id: int, limit: int = 10) -> dict[str, object]:
    settings = get_settings()
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    scrip = ScripMasterService(redis_client)
    if not scrip.ensure_loaded():
        raise AngelOneAuthError("Scrip master not loaded. Connect broker and retry.")

    bus = MarketRedisBus(settings.REDIS_URL)
    scan_payload = MarketScanner(bus, scrip).run_scan(db)
    scan_hits = scan_payload.get("hits") or []

    provider = StrategyDataProvider(bus, scrip)
    engine = IntradayEngine(provider)
    signals: list[StrategySignalCandidate] = engine.evaluate(limit=limit)
    generated_at = datetime.now(timezone.utc).isoformat()
    signal_dicts = [signal.to_dict() for signal in signals]

    universe_symbols: set[str] = {hit["symbol"] for hit in scan_hits if hit.get("symbol")}
    for token, symbol in provider.nifty_universe()[:20]:
        universe_symbols.add(symbol)

    ticks_loaded = 0
    try:
        for inst in scrip.nifty50_equities():
            if bus.get_tick(1, inst.token):
                ticks_loaded += 1
    except Exception:
        logger.debug("Tick count skipped during intraday scan")

    payload = {
        "generated_at": generated_at,
        "source": "live",
        "universe_size": len(universe_symbols),
        "history_loaded": ticks_loaded,
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
        "Intraday scan complete user_id=%s universe=%s scan_hits=%s picks=%s ticks=%s",
        user_id,
        len(universe_symbols),
        len(scan_hits),
        len(signal_dicts),
        ticks_loaded,
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
        "scan_hits": merged.get("scan_hits"),
        "min_score": merged.get("min_score", INTRADAY_MIN_SCORE),
        "signals": merged.get("signals", []),
    }
