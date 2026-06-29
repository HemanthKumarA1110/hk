"""Adaptive learning from trade journal outcomes."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from trading_shared.ai.constants import DEFAULT_WEIGHTS, REDIS_AI_WEIGHTS_KEY
from trading_shared.ai.scorer import AIScorer
from trading_shared.models import TradeJournalEntry

logger = logging.getLogger(__name__)


class AdaptiveLearner:
    LEARNING_RATE = 0.5

    def __init__(self, db: Session, redis_client):
        self.db = db
        self.redis = redis_client
        self.weights = self._load_weights()

    def _load_weights(self) -> dict[str, float]:
        cached = self.redis.get(REDIS_AI_WEIGHTS_KEY)
        if cached:
            return json.loads(cached)
        return DEFAULT_WEIGHTS.copy()

    def save_weights(self) -> dict[str, float]:
        self.redis.set(REDIS_AI_WEIGHTS_KEY, json.dumps(self.weights))
        return self.weights

    def learn_from_journal(self, limit: int = 100) -> dict[str, Any]:
        entries = (
            self.db.query(TradeJournalEntry)
            .order_by(TradeJournalEntry.created_at.desc())
            .limit(limit)
            .all()
        )
        if not entries:
            return {"updated": False, "weights": self.weights, "samples": 0}

        wins = [e for e in entries if (e.pnl or 0) > 0]
        losses = [e for e in entries if (e.pnl or 0) < 0]
        win_rate = len(wins) / len(entries) if entries else 0

        adjustments: dict[str, float] = {}
        for entry in entries:
            try:
                features = json.loads(entry.features_json or "{}")
            except json.JSONDecodeError:
                features = {}
            outcome_sign = 1.0 if (entry.pnl or 0) > 0 else -1.0
            for key in self.weights:
                feat_val = float(features.get(key, 50))
                if feat_val > 60:
                    adjustments[key] = adjustments.get(key, 0) + outcome_sign * self.LEARNING_RATE

        scorer = AIScorer(self.weights)
        self.weights = scorer.update_weights(adjustments)
        self.save_weights()

        logger.info("Adaptive learning: win_rate=%.2f samples=%s", win_rate, len(entries))
        return {
            "updated": True,
            "weights": self.weights,
            "samples": len(entries),
            "win_rate": round(win_rate, 4),
            "wins": len(wins),
            "losses": len(losses),
        }

    def get_scorer(self) -> AIScorer:
        return AIScorer(self.weights)
