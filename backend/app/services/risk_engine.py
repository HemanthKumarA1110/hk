from datetime import date
from typing import Optional

class RiskEngine:
    def __init__(self, equity: float = 100000.0):
        self.equity = equity
        self.max_loss_per_trade_pct = 1.0
        self.max_daily_loss_pct = 5.0
        self.max_trades_per_day = 10
        self.daily_loss = 0.0
        self.trade_count = 0
        self.current_day: Optional[date] = None

    def set_limits(
        self,
        max_loss_per_trade_pct: float = 1.0,
        max_daily_loss_pct: float = 5.0,
        max_trades_per_day: int = 10,
    ):
        self.max_loss_per_trade_pct = max_loss_per_trade_pct
        self.max_daily_loss_pct = max_daily_loss_pct
        self.max_trades_per_day = max_trades_per_day

    def _reset_daily(self):
        self.daily_loss = 0.0
        self.trade_count = 0

    def maybe_reset_day(self, trade_date: date):
        if self.current_day != trade_date:
            self.current_day = trade_date
            self._reset_daily()

    def can_trade(self, trade_date: Optional[date] = None) -> bool:
        if trade_date is not None:
            self.maybe_reset_day(trade_date)
        if self.trade_count >= self.max_trades_per_day:
            return False
        if self.daily_loss >= self.equity * (self.max_daily_loss_pct / 100.0):
            return False
        return True

    def position_size(self, entry: float, stoploss: float, risk_pct: float = 1.0) -> int:
        if stoploss == entry:
            return 0
        risk_amount = self.equity * (risk_pct / 100.0)
        stop_distance = abs(entry - stoploss)
        if stop_distance <= 0:
            return 0
        qty = int(risk_amount // stop_distance)
        return max(qty, 1)

    def register_trade(self, realized_pnl: float):
        self.trade_count += 1
        if realized_pnl < 0:
            self.daily_loss += abs(realized_pnl)

risk_engine = RiskEngine()
