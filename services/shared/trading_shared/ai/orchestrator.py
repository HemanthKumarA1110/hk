"""AI decision orchestrator — evaluates strategy signals and publishes decisions."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import redis
from sqlalchemy.orm import Session

from trading_shared.ai.constants import PUBSUB_AI_DECISIONS, REDIS_AI_DECISIONS_KEY, REDIS_AI_JOURNAL_INSIGHTS_KEY
from trading_shared.ai.decision_engine import DecisionEngine
from trading_shared.ai.features import FeatureExtractor
from trading_shared.ai.journal_analyzer import JournalAnalyzer
from trading_shared.ai.learning import AdaptiveLearner
from trading_shared.ai.regime import RegimeDetector
from trading_shared.config import get_settings
from trading_shared.market.redis_bus import MarketRedisBus
from trading_shared.market.scrip_master import ScripMasterService
from trading_shared.models import AIDecisionRecord, TradeJournalEntry
from trading_shared.strategies.data_provider import StrategyDataProvider
from trading_shared.strategies.orchestrator import StrategyOrchestrator

logger = logging.getLogger(__name__)


class AIOrchestrator:
    def __init__(self, db: Session):
        settings = get_settings()
        self.db = db
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.redis_bus = MarketRedisBus(settings.REDIS_URL)
        scrip = ScripMasterService(self.redis)
        data = StrategyDataProvider(self.redis_bus, scrip)
        self.learner = AdaptiveLearner(db, self.redis)
        settings = get_settings()
        self.decision_engine = DecisionEngine(
            FeatureExtractor(data, self.redis_bus),
            RegimeDetector(data),
            self.learner.get_scorer(),
            enter_threshold=settings.AI_DECISION_THRESHOLD,
        )
        self.journal_analyzer = JournalAnalyzer(db)

    def run(self) -> dict:
        generated_at = datetime.now(timezone.utc).isoformat()
        self.learner.learn_from_journal()

        all_signals: list[dict] = []
        for engine in ("scalping", "intraday", "swing"):
            cached = StrategyOrchestrator.get_cached(engine)
            all_signals.extend(cached.get("signals", []))

        open_positions = self._open_positions()
        decisions = []
        for signal in all_signals:
            symbol = signal.get("symbol", "")
            has_pos = symbol in open_positions
            pnl_pct = open_positions.get(symbol, 0.0)
            result = self.decision_engine.evaluate_signal(signal, has_pos, pnl_pct)
            decisions.append(result.to_dict())

        enter_decisions = [d for d in decisions if d["action"] in ("enter", "scale_in")]
        insights = self.journal_analyzer.analyze()

        payload = {
            "generated_at": generated_at,
            "decisions": decisions,
            "approved": enter_decisions,
            "rejected_count": sum(1 for d in decisions if d["action"] == "avoid"),
            "journal_insights": insights,
            "weights": self.learner.weights,
        }

        self.redis.setex(REDIS_AI_DECISIONS_KEY, 300, json.dumps(payload))
        self.redis.setex(REDIS_AI_JOURNAL_INSIGHTS_KEY, 600, json.dumps(insights))
        self.redis.publish(PUBSUB_AI_DECISIONS, json.dumps(payload))
        self._persist_decisions(decisions[:50])
        logger.info("AI run: %s signals → %s approved", len(decisions), len(enter_decisions))
        return payload

    def _open_positions(self) -> dict[str, float]:
        entries = (
            self.db.query(TradeJournalEntry)
            .filter(TradeJournalEntry.status == "open")
            .all()
        )
        result = {}
        for entry in entries:
            pnl_pct = 0.0
            if entry.entry_price and entry.current_price:
                pnl_pct = ((entry.current_price - entry.entry_price) / entry.entry_price) * 100
                if entry.side == "SELL":
                    pnl_pct = -pnl_pct
            result[entry.symbol] = pnl_pct
        return result

    def _persist_decisions(self, decisions: list[dict]) -> None:
        for item in decisions:
            self.db.add(
                AIDecisionRecord(
                    symbol=item["symbol"],
                    token=item["token"],
                    engine=item["engine"],
                    action=item["action"],
                    score=item["score"],
                    threshold=item["threshold"],
                    confidence=item["confidence"],
                    regime=item["regime"],
                    reasoning=json.dumps(item.get("reasoning", [])),
                    features_json=json.dumps(item.get("features", {})),
                    signal_json=json.dumps(item.get("signal", {})),
                    recommended_size_pct=item.get("recommended_size_pct", 100),
                )
            )
        self.db.commit()

    @staticmethod
    def get_cached() -> dict:
        settings = get_settings()
        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        raw = client.get(REDIS_AI_DECISIONS_KEY)
        return json.loads(raw) if raw else {"generated_at": None, "decisions": [], "approved": []}
