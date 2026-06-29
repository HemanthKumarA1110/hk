from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EngineType(str, Enum):
    SCALPING = "scalping"
    INTRADAY = "intraday"
    SWING = "swing"


class SignalSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Confirmation:
    name: str
    passed: bool
    weight: float
    detail: str = ""


@dataclass
class StrategySignalCandidate:
    engine: EngineType
    strategy_name: str
    symbol: str
    token: str
    side: SignalSide
    entry: float
    stoploss: float
    targets: list[float]
    trailing_stop: float
    timeframe: str
    score: float
    confidence: float
    risk_reward: float
    confirmations: list[Confirmation] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine": self.engine.value,
            "strategy_name": self.strategy_name,
            "symbol": self.symbol,
            "token": self.token,
            "side": self.side.value,
            "entry": float(round(self.entry, 2)),
            "stoploss": float(round(self.stoploss, 2)),
            "targets": [float(round(t, 2)) for t in self.targets],
            "trailing_stop": float(round(self.trailing_stop, 2)),
            "timeframe": self.timeframe,
            "score": float(round(self.score, 2)),
            "confidence": float(round(self.confidence, 4)),
            "risk_reward": float(round(self.risk_reward, 2)),
            "confirmations": [
                {
                    "name": c.name,
                    "passed": bool(c.passed),
                    "weight": float(c.weight),
                    "detail": c.detail,
                }
                for c in self.confirmations
            ],
            "metadata": self.metadata,
        }
