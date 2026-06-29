"""Core AI decision logic."""

from __future__ import annotations

from trading_shared.ai.constants import (
    DEFAULT_ENTER_THRESHOLD,
    DEFAULT_EXIT_THRESHOLD,
    DEFAULT_PARTIAL_BOOK_THRESHOLD,
    DEFAULT_SCALE_IN_THRESHOLD,
)
from trading_shared.ai.features import FeatureExtractor
from trading_shared.ai.reasoning import build_reasoning
from trading_shared.ai.regime import RegimeDetector
from trading_shared.ai.scorer import AIScorer
from trading_shared.ai.types import AIDecisionResult, DecisionAction, FeatureVector, MarketRegime


class DecisionEngine:
    def __init__(
        self,
        feature_extractor: FeatureExtractor,
        regime_detector: RegimeDetector,
        scorer: AIScorer,
        enter_threshold: float = DEFAULT_ENTER_THRESHOLD,
    ):
        self.features = feature_extractor
        self.regime_detector = regime_detector
        self.scorer = scorer
        self.enter_threshold = enter_threshold
        self.scale_in_threshold = DEFAULT_SCALE_IN_THRESHOLD
        self.partial_book_threshold = DEFAULT_PARTIAL_BOOK_THRESHOLD
        self.exit_threshold = DEFAULT_EXIT_THRESHOLD

    def evaluate_signal(
        self,
        signal: dict,
        has_open_position: bool = False,
        position_pnl_pct: float = 0.0,
    ) -> AIDecisionResult:
        underlying = signal.get("metadata", {}).get("underlying", "NIFTY")
        if isinstance(signal.get("metadata"), str):
            import json
            try:
                underlying = json.loads(signal["metadata"]).get("underlying", "NIFTY")
            except json.JSONDecodeError:
                pass
        regime = self.regime_detector.detect(underlying if signal.get("engine") == "scalping" else "NIFTY")
        feature_vector = self.features.extract(signal, regime)
        score = self.scorer.score(feature_vector)
        action, size_pct = self._pick_action(score, has_open_position, position_pnl_pct)
        confidence = min(score / 100, 1.0) * float(signal.get("confidence") or 0.7)
        reasoning = build_reasoning(action, score, self.enter_threshold, regime, feature_vector, signal)

        return AIDecisionResult(
            symbol=signal.get("symbol", ""),
            token=signal.get("token", ""),
            engine=signal.get("engine", ""),
            action=action,
            score=score,
            threshold=self.enter_threshold,
            confidence=confidence,
            regime=regime,
            reasoning=reasoning,
            features=feature_vector,
            signal=signal,
            recommended_size_pct=size_pct,
        )

    def _pick_action(
        self,
        score: float,
        has_open_position: bool,
        position_pnl_pct: float,
    ) -> tuple[DecisionAction, float]:
        if has_open_position:
            if score < self.exit_threshold:
                return DecisionAction.EXIT, 100.0
            if position_pnl_pct > 1.5 and score < self.partial_book_threshold:
                return DecisionAction.PARTIAL_BOOK, 50.0
            if self.scale_in_threshold <= score < self.enter_threshold:
                return DecisionAction.SCALE_IN, 40.0
            if score >= self.enter_threshold:
                return DecisionAction.HOLD, 100.0
            return DecisionAction.HOLD, 100.0

        if score >= self.enter_threshold:
            return DecisionAction.ENTER, 100.0
        if score >= self.scale_in_threshold:
            return DecisionAction.SCALE_IN, 50.0
        return DecisionAction.AVOID, 0.0
