from pydantic import BaseModel, Field


class OrderCreateRequest(BaseModel):
    symbol: str = Field(description="RELIANCE-EQ or NSE:RELIANCE")
    symboltoken: str | None = Field(default=None, description="Angel One symbol token when known")
    exchange: str = "NSE"
    side: str = Field(description="BUY or SELL")
    qty: int = Field(gt=0)
    order_type: str = Field(default="MARKET", description="MARKET or LIMIT")
    price: float = Field(default=0, ge=0)
    product: str = Field(default="INTRADAY", description="INTRADAY, DELIVERY, MARGIN")
    stoploss: float | None = Field(default=None, gt=0)
    variety: str = "NORMAL"


class OrderModifyRequest(BaseModel):
    order_id: str
    variety: str = "NORMAL"
    order_type: str | None = None
    price: float | None = None
    qty: int | None = None
    trigger_price: float | None = None


class OrderCancelRequest(BaseModel):
    order_id: str
    variety: str = "NORMAL"


class OrderResponse(BaseModel):
    id: int
    broker_order_id: str | None
    symbol: str
    side: str
    qty: int
    price: float
    order_type: str
    product: str
    status: str
    message: str | None = None
    risk_approved: bool = True
    risk_reason: str | None = None
    execution_mode: str | None = None


class TradingModeRequest(BaseModel):
    mode: str = Field(description="paper or live")
