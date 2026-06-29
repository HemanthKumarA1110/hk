from pydantic import BaseModel, Field


class RiskLimitsUpdate(BaseModel):
    max_loss_per_trade_pct: float | None = None
    max_daily_loss_pct: float | None = None
    max_drawdown_pct: float | None = None
    max_capital_allocation_pct: float | None = None
    max_trades_per_day: int | None = None
    risk_per_trade_pct: float | None = None


class EquityUpdate(BaseModel):
    equity: float = Field(gt=0)


class TradeEvaluationRequest(BaseModel):
    entry: float = Field(gt=0)
    stoploss: float = Field(gt=0)
    side: str = "BUY"


class RegisterTradeRequest(BaseModel):
    realized_pnl: float
    notional: float = 0.0
