"""Production risk management engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone


@dataclass
class RiskLimits:
    max_loss_per_trade_pct: float = 1.0
    max_daily_loss_pct: float = 5.0
    max_drawdown_pct: float = 15.0
    max_capital_allocation_pct: float = 80.0
    max_trades_per_day: int = 20
    risk_per_trade_pct: float = 1.0


@dataclass
class RiskState:
    equity: float = 100000.0
    available_capital: float = 100000.0
    daily_pnl: float = 0.0
    daily_loss: float = 0.0
    trade_count: int = 0
    peak_equity: float = 100000.0
    current_drawdown_pct: float = 0.0
    exposure: float = 0.0
    trading_halted: bool = False
    halt_reason: str = ""
    current_day: str = field(default_factory=lambda: date.today().isoformat())

    def to_dict(self) -> dict:
        return {
            "equity": round(self.equity, 2),
            "available_capital": round(self.available_capital, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_loss": round(self.daily_loss, 2),
            "trade_count": self.trade_count,
            "peak_equity": round(self.peak_equity, 2),
            "current_drawdown_pct": round(self.current_drawdown_pct, 2),
            "exposure": round(self.exposure, 2),
            "trading_halted": self.trading_halted,
            "halt_reason": self.halt_reason,
            "current_day": self.current_day,
        }


class RiskEngine:
    def __init__(self, limits: RiskLimits | None = None, state: RiskState | None = None):
        self.limits = limits or RiskLimits()
        self.state = state or RiskState()
        if self.state.peak_equity <= 0:
            self.state.peak_equity = self.state.equity

    def maybe_reset_day(self, today: date | None = None) -> None:
        today = today or date.today()
        if self.state.current_day != today.isoformat():
            self.state.current_day = today.isoformat()
            self.state.daily_pnl = 0.0
            self.state.daily_loss = 0.0
            self.state.trade_count = 0
            if not self.state.trading_halted or "daily" in self.state.halt_reason.lower():
                self.state.trading_halted = False
                self.state.halt_reason = ""

    def update_equity(self, equity: float) -> None:
        self.state.equity = equity
        self.state.available_capital = max(equity - self.state.exposure, 0)
        if equity > self.state.peak_equity:
            self.state.peak_equity = equity
        if self.state.peak_equity > 0:
            self.state.current_drawdown_pct = ((self.state.peak_equity - equity) / self.state.peak_equity) * 100
        if self.state.current_drawdown_pct >= self.limits.max_drawdown_pct:
            self.state.trading_halted = True
            self.state.halt_reason = "Max drawdown breached"

    def can_trade(self) -> tuple[bool, str]:
        self.maybe_reset_day()
        if self.state.trading_halted:
            return False, self.state.halt_reason or "Trading halted"
        if self.state.trade_count >= self.limits.max_trades_per_day:
            return False, "Max trades per day reached"
        max_daily_loss = self.state.equity * (self.limits.max_daily_loss_pct / 100)
        if self.state.daily_loss >= max_daily_loss:
            self.state.trading_halted = True
            self.state.halt_reason = "Daily max loss reached"
            return False, self.state.halt_reason
        max_allocation = self.state.equity * (self.limits.max_capital_allocation_pct / 100)
        if self.state.exposure >= max_allocation:
            return False, "Max capital allocation reached"
        return True, "ok"

    def position_size(self, entry: float, stoploss: float, risk_pct: float | None = None) -> dict:
        risk_pct = risk_pct or self.limits.risk_per_trade_pct
        if entry <= 0 or stoploss == entry:
            return {"qty": 0, "risk_amount": 0, "message": "Invalid entry/stoploss"}
        risk_amount = self.state.equity * (risk_pct / 100)
        stop_distance = abs(entry - stoploss)
        qty = int(risk_amount // stop_distance) if stop_distance > 0 else 0
        qty = max(qty, 1)
        notional = qty * entry
        max_notional = self.state.equity * (self.limits.max_capital_allocation_pct / 100) - self.state.exposure
        if notional > max_notional > 0:
            qty = max(int(max_notional // entry), 0)
        return {
            "qty": qty,
            "risk_amount": round(risk_amount, 2),
            "notional": round(qty * entry, 2),
            "risk_pct": risk_pct,
        }

    def register_trade(self, realized_pnl: float, notional: float = 0.0) -> None:
        self.maybe_reset_day()
        self.state.trade_count += 1
        self.state.daily_pnl += realized_pnl
        if realized_pnl < 0:
            self.state.daily_loss += abs(realized_pnl)
        if notional > 0:
            self.state.exposure += notional
        self.update_equity(self.state.equity + realized_pnl)

    def dynamic_stoploss(self, entry: float, side: str, atr: float = 0.0) -> float:
        buffer = atr * 1.5 if atr > 0 else entry * 0.005
        if side.upper() == "BUY":
            return round(entry - buffer, 2)
        return round(entry + buffer, 2)

    def trailing_stop(self, current_price: float, side: str, trail_points: float) -> float:
        if side.upper() == "BUY":
            return round(current_price - trail_points, 2)
        return round(current_price + trail_points, 2)

    def break_even_stop(self, entry: float, side: str, buffer: float = 0.05) -> float:
        if side.upper() == "BUY":
            return round(entry + buffer, 2)
        return round(entry - buffer, 2)

    def risk_meter(self) -> dict:
        self.maybe_reset_day()
        max_daily = self.state.equity * (self.limits.max_daily_loss_pct / 100)
        daily_usage = (self.state.daily_loss / max_daily) * 100 if max_daily > 0 else 0
        allocation_usage = (self.state.exposure / max(self.state.equity, 1)) * 100
        can_trade, reason = self.can_trade()
        return {
            "can_trade": can_trade,
            "reason": reason,
            "daily_loss_used_pct": round(min(daily_usage, 100), 2),
            "drawdown_pct": round(self.state.current_drawdown_pct, 2),
            "allocation_used_pct": round(allocation_usage, 2),
            "status": "ok" if can_trade else "blocked",
            "limits": {
                "max_daily_loss_pct": self.limits.max_daily_loss_pct,
                "max_drawdown_pct": self.limits.max_drawdown_pct,
                "max_capital_allocation_pct": self.limits.max_capital_allocation_pct,
                "max_trades_per_day": self.limits.max_trades_per_day,
                "risk_per_trade_pct": self.limits.risk_per_trade_pct,
            },
            "state": self.state.to_dict(),
        }
