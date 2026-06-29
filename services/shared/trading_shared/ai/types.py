"""AI decision engine types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DecisionAction(str, Enum):
    ENTER = "enter"
    AVOID = "avoid"
    EXIT = "exit"
    SCALE_IN = "scale_in"
    PARTIAL_BOOK = "partial_book"
    HOLD = "hold"


class MarketRegime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"


@dataclass
class FeatureVector:
    trend: float = 0.0
    volume: float = 0.0
    volatility: float = 0.0
    oi: float = 0.0
    greeks: float = 0.0
    sentiment: float = 0.0
    sector_strength: float = 0.0
    price_action: float = 0.0
    risk_reward: float = 0.0
    market_regime: float = 0.0
    strategy_score: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return {
            "trend": self.trend,
            "volume": self.volume,
            "volatility": self.volatility,
            "oi": self.oi,
            "greeks": self.greeks,
            "sentiment": self.sentiment,
            "sector_strength": self.sector_strength,
            "price_action": self.price_action,
            "risk_reward": self.risk_reward,
            "market_regime": self.market_regime,
            "strategy_score": self.strategy_score,
        }


@dataclass
class AIDecisionResult:
    symbol: str
    token: str
    engine: str
    action: DecisionAction
    score: float
    threshold: float
    confidence: float
    regime: MarketRegime
    reasoning: list[str] = field(default_factory=list)
    features: FeatureVector | None = None
    signal: dict[str, Any] = field(default_factory=dict)
    recommended_size_pct: float = 100.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "token": self.token,
            "engine": self.engine,
            "action": self.action.value,
            "score": round(self.score, 2),
            "threshold": self.threshold,
            "confidence": round(self.confidence, 4),
            "regime": self.regime.value,
            "reasoning": self.reasoning,
            "features": self.features.to_dict() if self.features else {},
            "signal": self.signal,
            "recommended_size_pct": self.recommended_size_pct,
        }
