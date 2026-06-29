from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime

class Order(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    symbol: str
    side: str
    qty: int
    price: float
    status: str
    mode: str
    order_type: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class PositionEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: Optional[int]
    symbol: str
    side: str
    qty: int
    entry_price: float
    stoploss: float
    target: float
    status: str
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    closed_at: Optional[datetime] = None
    pnl: Optional[float] = None
