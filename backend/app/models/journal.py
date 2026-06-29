from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime

class Portfolio(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int
    capital: float
    available_margin: float
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0
    roi: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Position(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
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

class Alert(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    alert_type: str
    symbol: str
    message: str
    delivered: bool = False
    ts: datetime = Field(default_factory=datetime.utcnow)
