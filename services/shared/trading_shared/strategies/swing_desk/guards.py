"""Trading guards for swing desk auto-trading."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MIN = 15
NO_ENTRY_AFTER = (15, 0)


def _now_ist() -> datetime:
    return datetime.now(tz=IST)


def is_market_session() -> bool:
    now = _now_ist()
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return (9 * 60 + 15) <= t <= (15 * 60 + 30)


def can_enter_new_trades() -> bool:
    now = _now_ist()
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    open_m = MARKET_OPEN_HOUR * 60 + MARKET_OPEN_MIN
    cutoff = NO_ENTRY_AFTER[0] * 60 + NO_ENTRY_AFTER[1]
    return open_m <= t < cutoff


def guard_status(state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    trades_today = int(state.get("trades_today") or 0)
    daily_pnl = float(state.get("daily_pnl") or 0)
    max_trades = int(config.get("max_trades_per_day") or 5)
    max_loss = float(config.get("max_daily_loss_inr") or 5000)
    max_open = int(config.get("max_open_positions") or 5)
    open_count = len(state.get("active_positions") or [])
    auto_on = bool(config.get("auto_trading_enabled"))

    alerts: list[str] = []
    can_enter = auto_on and can_enter_new_trades()
    if not auto_on:
        alerts.append("Auto trading is off")
        can_enter = False
    if not is_market_session():
        alerts.append("Outside market hours")
        can_enter = False
    if not can_enter_new_trades():
        alerts.append("No new entries after 3:00 PM IST")
        can_enter = False
    if trades_today >= max_trades:
        alerts.append(f"Max trades per day reached ({max_trades})")
        can_enter = False
    if open_count >= max_open:
        alerts.append(f"Max open positions reached ({max_open})")
        can_enter = False
    if daily_pnl <= -max_loss:
        alerts.append(f"Daily max loss ₹{max_loss:,.0f} reached")
        can_enter = False

    return {
        "can_enter": can_enter,
        "can_enter_paper": can_enter,
        "must_force_exit": False,
        "trades_today": trades_today,
        "open_positions": open_count,
        "max_open_positions": max_open,
        "daily_pnl": round(daily_pnl, 2),
        "alerts": alerts,
    }
