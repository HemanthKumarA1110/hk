from pydantic import BaseModel, Field


class BacktestRunRequest(BaseModel):
    engine: str = Field(description="scalping | intraday | swing")
    symbol: str = "NIFTY"
    token: str | None = None
    exchange: str = "NSE"
    interval: str = "5m"
    from_date: str = Field(description="YYYY-MM-DD")
    to_date: str = Field(description="YYYY-MM-DD")
    initial_capital: float = Field(default=100000, gt=0)
    risk_pct: float = Field(default=1.0, gt=0, le=5)
    max_loss_per_trade_pct: float = 1.0
    max_daily_loss_pct: float = 5.0
    max_trades_per_day: int = 10
    use_demo_data: bool = False
    strategy_code: str | None = Field(default=None, description="Optional INTRA-* / SWING-* catalog code")
    auto_pick_universe: bool = Field(default=False, description="Intraday/swing: screen Nifty 50 universe")
    top_n: int = Field(default=10, ge=1, le=20, description="Intraday: top symbols to backtest individually")
    max_open_positions: int = Field(default=5, ge=1, le=10, description="Swing: max concurrent portfolio positions")
    ai_entry: bool = Field(default=False, description="Apply AI entry confirmation filter")
    ai_exit: bool = Field(default=False, description="Apply AI dynamic exit on open trades")


class BacktestRunCreated(BaseModel):
    run_id: int
    status: str
    message: str


class BacktestTradeOut(BaseModel):
    entry_ts: str
    exit_ts: str
    side: str
    symbol: str
    entry_price: float
    exit_price: float
    qty: int
    pnl: float
    return_pct: float
    stoploss: float
    target: float


class BacktestMetrics(BaseModel):
    initial_capital: float
    final_capital: float
    total_trades: int
    win_rate: float
    max_drawdown: float
    profit_factor: float
    total_pnl: float
    avg_trade_pnl: float


class BacktestRunResponse(BaseModel):
    run_id: int
    status: str
    engine: str
    symbol: str
    interval: str
    from_date: str
    to_date: str
    data_source: str
    metrics: BacktestMetrics | None = None
    equity_curve: list[float] = []
    trades: list[BacktestTradeOut] = []
    error_message: str | None = None
    created_at: str | None = None
    completed_at: str | None = None
