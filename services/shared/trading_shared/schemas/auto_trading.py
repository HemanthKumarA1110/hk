from pydantic import BaseModel, Field


class AutoTradingConfigUpdate(BaseModel):
    engine: str | None = Field(
        default=None,
        description="scalping, intraday, or swing — required when updating per-engine settings",
    )
    enabled: bool | None = None
    max_orders_per_day: int | None = Field(default=None, ge=1, le=500)
    max_order_amount: float | None = Field(
        default=None,
        ge=0,
        le=50_000_000,
        description="Max INR notional per single order; qty = amount / entry (scaled by AI size %)",
    )
    max_daily_loss_pct: float | None = Field(default=None, gt=0, le=100)
