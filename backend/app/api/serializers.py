from pydantic import BaseModel
from typing import List, Optional

class BacktestRequest(BaseModel):
    strategy: str
    symbol: str
    timeframe: str
    risk_pct: Optional[float] = 1.0
    target_rr: Optional[float] = 2.0
    max_loss_per_trade_pct: Optional[float] = 1.0
    max_daily_loss_pct: Optional[float] = 5.0
    max_trades_per_day: Optional[int] = 10

class BacktestResult(BaseModel):
    initial_capital: float
    final_capital: float
    total_trades: int
    win_rate: float
    max_drawdown: float
    equity_curve: List[float]
    trades: List[dict]

class SignalResponse(BaseModel):
    strategy: str
    symbol: str
    side: str
    entry: float
    stoploss: float
    targets: List[float]
    trailing_stop: Optional[float]
    confidence: Optional[float]
    timeframe: Optional[str]
    risk_reward: Optional[float]

class RiskMetrics(BaseModel):
    current_exposure: float
    max_daily_loss: float
    strategy_count: int
    risk_status: str

class MarketSummary(BaseModel):
    daily_volume: int
    top_symbol: str
    market_mood: str

class DashboardOverview(BaseModel):
    total_capital: float
    available_margin: float
    daily_pnl: float
    weekly_pnl: float
    monthly_pnl: float
    win_rate: float
    risk_reward_ratio: float
    total_trades: int
    current_open_trades: int
    max_drawdown: float
    roi: float
    risk: RiskMetrics
    market_summary: MarketSummary
    equity_curve: List[float]
    recent_trades: List[dict]
    last_updated: str
