"""Multi-confirmation scoring for strategy signals."""

from __future__ import annotations

from trading_shared.strategies.types import Confirmation, StrategySignalCandidate

SCALPING_MIN_SCORE = 80.0
INTRADAY_MIN_SCORE = 65.0
SWING_MIN_SCORE = 60.0


def score_confirmations(confirmations: list[Confirmation]) -> float:
    total_weight = sum(c.weight for c in confirmations if c.weight > 0)
    if total_weight <= 0:
        return 0.0
    earned = sum(c.weight for c in confirmations if c.passed)
    return round((earned / total_weight) * 100, 2)


def confidence_from_score(score: float, confirmations: list[Confirmation]) -> float:
    passed = sum(1 for c in confirmations if c.passed)
    total = max(len(confirmations), 1)
    blend = (score / 100) * 0.7 + (passed / total) * 0.3
    return round(min(max(blend, 0.0), 1.0), 4)


def filter_candidates(
    candidates: list[StrategySignalCandidate],
    min_score: float,
) -> list[StrategySignalCandidate]:
    return sorted(
        [c for c in candidates if c.score >= min_score],
        key=lambda item: item.score,
        reverse=True,
    )


def rank_top(candidates: list[StrategySignalCandidate], limit: int = 10) -> list[StrategySignalCandidate]:
    return sorted(candidates, key=lambda item: (item.score, item.confidence), reverse=True)[:limit]
