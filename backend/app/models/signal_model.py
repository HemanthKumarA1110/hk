from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime

class Signal(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    strategy_id: int
    symbol: str
    side: str
    entry: float
    stoploss: Optional[float]
    target: Optional[float]
    confidence: Optional[float]
    ts: datetime = Field(default_factory=datetime.utcnow)
