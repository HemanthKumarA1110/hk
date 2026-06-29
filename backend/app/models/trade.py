from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime

class Trade(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: Optional[str]
    signal_id: Optional[int]
    symbol: str
    side: str
    qty: int
    price: float
    status: str
    ts: datetime = Field(default_factory=datetime.utcnow)
