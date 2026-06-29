"""Weighted AI scoring engine."""

from __future__ import annotations

from trading_shared.ai.constants import DEFAULT_WEIGHTS
from trading_shared.ai.types import FeatureVector


class AIScorer:
    def __init__(self, weights: dict[str, float] | None = None):
        self.weights = weights or DEFAULT_WEIGHTS.copy()

    def score(self, features: FeatureVector) -> float:
        vector = features.to_dict()
        # Blend strategy engine score (30%) with AI feature score (70%)
        strategy_component = vector.pop("strategy_score", 0) * 0.3
        total_weight = sum(self.weights.values())
        if total_weight <= 0:
            return strategy_component

        weighted = 0.0
        for key, weight in self.weights.items():
            weighted += vector.get(key, 0) * weight
        ai_component = (weighted / total_weight) * 0.7
        return round(min(max(strategy_component + ai_component, 0), 100), 2)

    def update_weights(self, adjustments: dict[str, float]) -> dict[str, float]:
        for key, delta in adjustments.items():
            if key in self.weights:
                self.weights[key] = max(1.0, min(self.weights[key] + delta, 25.0))
        return self.weights
