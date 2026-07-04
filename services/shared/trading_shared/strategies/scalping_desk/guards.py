"""Safety guards for scalping desk auto-trading."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from trading_shared.strategies.scalping_desk.constants import (
    DEFAULT_MAX_TRADES,
    FORCE_EXIT_HOUR_IST,
    MIN_TRADE_GAP_MINUTES,
)

IST = ZoneInfo("Asia/Kolkata")


def guard_status(
    state: dict[str, Any],
    config: dict[str, Any],
    *,
    daily_stop: dict[str, Any] | None = None,
    expiry_handler: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate all safety guards and return enforcement flags."""
    daily_pnl = float(state.get("daily_pnl") or 0)
    trades_today = int(state.get("trades_today") or 0)
    max_loss = float(config.get("max_loss_per_day") or 5000)
    max_trades = int(config.get("max_trades_per_day") or DEFAULT_MAX_TRADES)
    if expiry_handler and (
        expiry_handler.get("is_expiry") or expiry_handler.get("is_special_session")
    ):
        max_trades = min(max_trades, int(expiry_handler.get("max_trades", max_trades)))
    last_trade_at = state.get("last_trade_at")
    stream_connected = bool(state.get("stream_connected", True))
    auto_on = bool(config.get("auto_trading_enabled"))

    stop_decision = daily_stop or {}
    ai_stopped = bool(state.get("ai_daily_stop") or stop_decision.get("stop_trading"))

    now_ist = datetime.now(IST)
    force_exit = now_ist.hour > FORCE_EXIT_HOUR_IST[0] or (
        now_ist.hour == FORCE_EXIT_HOUR_IST[0] and now_ist.minute >= FORCE_EXIT_HOUR_IST[1]
    )

    loss_breached = daily_pnl <= -abs(max_loss)
    trades_capped = trades_today >= max_trades
    gap_ok = True
    if last_trade_at:
        try:
            last = datetime.fromisoformat(last_trade_at)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            gap_ok = datetime.now(timezone.utc) - last >= timedelta(minutes=MIN_TRADE_GAP_MINUTES)
        except ValueError:
            gap_ok = True

    from trading_shared.strategies.scalping_desk.expiry_day_handler import expiry_blocks_new_entries

    expiry_blocked = expiry_blocks_new_entries(expiry_handler)

    can_enter = (
        auto_on
        and not loss_breached
        and not trades_capped
        and not ai_stopped
        and not expiry_blocked
        and gap_ok
        and not force_exit
        and stream_connected
    )

    can_enter_paper = (
        not loss_breached
        and not trades_capped
        and not ai_stopped
        and not expiry_blocked
        and gap_ok
        and not force_exit
        and stream_connected
    )

    alerts = []
    if ai_stopped:
        reason = state.get("ai_daily_stop_reason") or stop_decision.get("reason") or "AI locked profits for today"
        alerts.append(f"AI daily stop — {reason}")
    if loss_breached:
        alerts.append("Daily max loss reached — new entries disabled")
    if trades_capped:
        alerts.append("Max trades ceiling reached (hard limit)")
    if force_exit:
        alerts.append("Market close cutoff (3:15 PM IST) — force exit active")
    if auto_on and not stream_connected:
        alerts.append("Stream disconnected — auto trading paused")
    if not gap_ok:
        alerts.append(f"Minimum {MIN_TRADE_GAP_MINUTES}m gap between trades")
    if expiry_handler and expiry_handler.get("warning"):
        alerts.append(expiry_handler["warning"])

    return {
        "can_enter": can_enter,
        "can_enter_paper": can_enter_paper,
        "can_auto_trade": auto_on and stream_connected and not loss_breached and not ai_stopped,
        "force_exit": force_exit,
        "loss_breached": loss_breached,
        "trades_capped": trades_capped,
        "ai_daily_stop": ai_stopped,
        "ai_daily_stop_reason": state.get("ai_daily_stop_reason") or stop_decision.get("reason"),
        "gap_ok": gap_ok,
        "stream_connected": stream_connected,
        "alerts": alerts,
        "daily_pnl": daily_pnl,
        "trades_today": trades_today,
        "wins_today": int(state.get("wins_today") or 0),
        "consecutive_wins": int(state.get("consecutive_wins") or 0),
        "consecutive_losses": int(state.get("consecutive_losses") or 0),
        "max_loss_per_day": max_loss,
        "max_trades_per_day": max_trades,
        "max_trades_is_ceiling": True,
        "loss_guard_pct": min(abs(daily_pnl) / max(abs(max_loss), 1) * 100, 100) if max_loss else 0,
        "daily_stop": stop_decision,
        "expiry_handler": expiry_handler,
    }
