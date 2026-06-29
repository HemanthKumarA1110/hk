"""Run all strategy engines and persist signals."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import redis
from sqlalchemy.orm import Session

from trading_shared.config import get_settings
from trading_shared.market.redis_bus import MarketRedisBus
from trading_shared.market.scrip_master import ScripMasterService
from trading_shared.models import StrategySignal
from trading_shared.strategies.data_provider import StrategyDataProvider
from trading_shared.strategies.intraday_engine import IntradayEngine
from trading_shared.strategies.scalping_engine import ScalpingEngine
from trading_shared.strategies.swing_engine import SwingEngine
from trading_shared.strategies.types import StrategySignalCandidate

logger = logging.getLogger(__name__)

REDIS_SCALPING_KEY = "strategy:signals:scalping"
REDIS_INTRADAY_KEY = "strategy:signals:intraday"
REDIS_SWING_KEY = "strategy:signals:swing"
PUBSUB_STRATEGY_SIGNALS = "strategy:signals"


class StrategyOrchestrator:
    def __init__(self, db: Session | None = None):
        settings = get_settings()
        self.settings = settings
        self.db = db
        self.redis_raw = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.redis_bus = MarketRedisBus(settings.REDIS_URL)
        self.scrip_service = ScripMasterService(self.redis_raw)
        self.data = StrategyDataProvider(self.redis_bus, self.scrip_service)
        self.scalping = ScalpingEngine(self.data)
        self.intraday = IntradayEngine(self.data)
        self.swing = SwingEngine(self.data)

    def run_all(self) -> dict:
        generated_at = datetime.now(timezone.utc).isoformat()
        scalping = [s.to_dict() for s in self.scalping.evaluate()]
        intraday = [s.to_dict() for s in self.intraday.evaluate()]
        swing = [s.to_dict() for s in self.swing.evaluate()]

        payload = {
            "generated_at": generated_at,
            "scalping": scalping,
            "intraday": intraday,
            "swing": swing,
        }

        self.redis_raw.setex(REDIS_SCALPING_KEY, 300, json.dumps({"generated_at": generated_at, "signals": scalping}))
        self.redis_raw.setex(REDIS_INTRADAY_KEY, 300, json.dumps({"generated_at": generated_at, "signals": intraday}))
        self.redis_raw.setex(REDIS_SWING_KEY, 300, json.dumps({"generated_at": generated_at, "signals": swing}))
        self.redis_raw.publish(PUBSUB_STRATEGY_SIGNALS, json.dumps(payload))

        if self.db:
            self._persist_signals(scalping + intraday + swing)

        logger.info(
            "Strategy run complete: scalping=%s intraday=%s swing=%s",
            len(scalping),
            len(intraday),
            len(swing),
        )
        return payload

    def _persist_signals(self, signals: list[dict]) -> None:
        assert self.db is not None
        for item in signals[:50]:
            self.db.add(
                StrategySignal(
                    engine=item["engine"],
                    strategy_name=item["strategy_name"],
                    symbol=item["symbol"],
                    token=item["token"],
                    side=item["side"],
                    entry=item["entry"],
                    stoploss=item["stoploss"],
                    target=item["targets"][0] if item.get("targets") else item["entry"],
                    trailing_stop=item["trailing_stop"],
                    timeframe=item["timeframe"],
                    score=item["score"],
                    confidence=item["confidence"],
                    risk_reward=item["risk_reward"],
                    confirmations=json.dumps(item.get("confirmations", [])),
                    metadata=json.dumps(item.get("metadata", {})),
                    status="active",
                )
            )
        self.db.commit()

    @staticmethod
    def get_cached(engine: str) -> dict:
        settings = get_settings()
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        key_map = {
            "scalping": REDIS_SCALPING_KEY,
            "intraday": REDIS_INTRADAY_KEY,
            "swing": REDIS_SWING_KEY,
        }
        raw = client.get(key_map.get(engine, REDIS_INTRADAY_KEY))
        return json.loads(raw) if raw else {"generated_at": None, "signals": []}
