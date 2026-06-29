from pydantic import BaseModel
from typing import Optional, List

class Health(BaseModel):
    status: str

class SignalCreate(BaseModel):
    strategy_id: int
    symbol: str
    side: str
    entry: float
    stoploss: Optional[float]
    target: Optional[float]
    confidence: Optional[float]

class SignalPayload(BaseModel):
    strategy: str
    symbol: str
    side: str
    entry: float
    stoploss: float
    targets: List[float]
    trailing_stop: Optional[float] = None
    confidence: Optional[float] = None
    timeframe: Optional[str] = None
    risk_reward: Optional[float] = None

class PositionSizing(BaseModel):
    qty: int
    risk_amount: float
    stop_distance: float
