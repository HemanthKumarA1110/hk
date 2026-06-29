import pytest

from trading_shared.ai.scorer import AIScorer
from trading_shared.ai.types import FeatureVector


def test_ai_scorer_high_score():
    scorer = AIScorer()
    features = FeatureVector(
        trend=90,
        volume=85,
        volatility=70,
        oi=80,
        greeks=75,
        sentiment=70,
        sector_strength=80,
        price_action=85,
        risk_reward=90,
        market_regime=80,
        strategy_score=85,
    )
    score = scorer.score(features)
    assert score >= 75


def test_ai_scorer_low_score():
    scorer = AIScorer()
    features = FeatureVector(strategy_score=30, trend=20, volume=20, risk_reward=20)
    score = scorer.score(features)
    assert score < 60
