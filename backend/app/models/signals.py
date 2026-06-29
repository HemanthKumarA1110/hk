from typing import Optional
from pydantic import BaseModel

class SignalPayload(BaseModel):
    strategy: str
    symbol: str
    side: str
    entry: float
    stoploss: float
    targets: list[float]
    trailing_stop: Optional[float] = None
    confidence: Optional[float] = None
    timeframe: Optional[str] = None
    risk_reward: Optional[float] = None

class PositionSizing(BaseModel):
    qty: int
    risk_amount: float
    stop_distance: float
