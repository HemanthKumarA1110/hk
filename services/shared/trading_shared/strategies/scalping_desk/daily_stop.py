"""AI daily stop — end trading early after successful streak, based on market conditions."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

AI_DAILY_STOP_THRESHOLD = 72


def trading_day_key(now: datetime | None = None) -> str:
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)
    return now.strftime("%Y-%m-%d")


def maybe_reset_daily_state(state: dict[str, Any]) -> dict[str, Any]:
    """Reset daily counters when IST trading day rolls over."""
    today = trading_day_key()
    if state.get("trading_day") == today:
        return state
    state["trading_day"] = today
    state["daily_pnl"] = 0
    state["trades_today"] = 0
    state["wins_today"] = 0
    state["consecutive_wins"] = 0
    state["consecutive_losses"] = 0
    state["ai_daily_stop"] = False
    state["ai_daily_stop_reason"] = None
    state["ai_daily_stop_confidence"] = 0
    state["ai_daily_stop_at"] = None
    state["session_start_capital"] = None
    state["session_capital_source"] = None
    return state


def record_trade_result(state: dict[str, Any], pnl: float) -> dict[str, Any]:
    """Update win/loss streak counters after a closed trade."""
    if pnl > 0:
        state["consecutive_wins"] = int(state.get("consecutive_wins") or 0) + 1
        state["consecutive_losses"] = 0
    else:
        state["consecutive_wins"] = 0
        state["consecutive_losses"] = int(state.get("consecutive_losses") or 0) + 1
    return state


def evaluate_ai_daily_stop(
    state: dict[str, Any],
    config: dict[str, Any],
    market_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    AI decides whether to stop trading for the day after early wins.
    max_trades_per_day is a ceiling — not a target to fill.
    """
    ctx = market_context or {}
    trades_today = int(state.get("trades_today") or 0)
    wins_today = int(state.get("wins_today") or 0)
    consecutive_wins = int(state.get("consecutive_wins") or 0)
    daily_pnl = float(state.get("daily_pnl") or 0)
    capital = float(config.get("capital") or 100_000)
    max_trades = int(config.get("max_trades_per_day") or 5)

    if state.get("ai_daily_stop"):
        return {
            "stop_trading": True,
            "confidence": float(state.get("ai_daily_stop_confidence") or 90),
            "reason": state.get("ai_daily_stop_reason") or "AI stopped trading for today",
            "consecutive_wins": consecutive_wins,
            "trades_today": trades_today,
            "wins_today": wins_today,
            "daily_pnl": daily_pnl,
            "max_trades_ceiling": max_trades,
            "locked": True,
        }

    if trades_today == 0 or daily_pnl <= 0:
        return _no_stop(consecutive_wins, trades_today, wins_today, daily_pnl, max_trades)

    regime = str(ctx.get("regime") or "RANGING")
    vol_ratio = float(ctx.get("volume_ratio") or 1)
    trend_strength = float(ctx.get("trend_strength") or 0)
    win_rate = wins_today / trades_today if trades_today else 0

    score = 0.0
    reasons: list[str] = []

    if consecutive_wins >= 2:
        score = 68 + min(consecutive_wins - 2, 2) * 8
        reasons.append(f"{consecutive_wins} consecutive wins · ₹{daily_pnl:.0f} profit")

        if consecutive_wins >= 3:
            score += 12
            reasons.append("3-win streak — protect gains")

        if win_rate == 1.0 and trades_today >= 2:
            score += 10
            reasons.append(f"perfect day {wins_today}/{trades_today}")

        if daily_pnl >= capital * 0.012:
            score += 10
            reasons.append("daily profit target met")

        if daily_pnl >= capital * 0.02:
            score += 8
            reasons.append("strong day — lock profits")

        # Market conditions: stop sooner when edge fades
        if regime in ("RANGING", "LOW_VOLATILITY"):
            score += 8
            reasons.append("sideways market — edge fading")
        if regime == "HIGH_VOLATILITY" and consecutive_wins >= 2:
            score += 6
            reasons.append("high vol — reversal risk after wins")
        if vol_ratio < 1.25:
            score += 8
            reasons.append("volume drying up")
        if trend_strength < 0.05:
            score += 5
            reasons.append("weak trend — chop risk")

        # Keep trading only when trend + volume still strong and only 2 wins
        if (
            consecutive_wins == 2
            and regime in ("TRENDING_UP", "TRENDING_DOWN")
            and vol_ratio >= 1.45
            and trend_strength >= 0.08
            and daily_pnl < capital * 0.015
        ):
            score -= 18
            reasons.append("strong trend + volume — one more setup allowed")

    elif wins_today >= 3 and daily_pnl > 0 and win_rate >= 0.75:
        score = 78
        reasons.append(f"{wins_today}/{trades_today} wins — secure ₹{daily_pnl:.0f}")

    stop = score >= AI_DAILY_STOP_THRESHOLD
    return {
        "stop_trading": stop,
        "confidence": round(min(score, 98), 1) if stop else round(max(score, 0), 1),
        "reason": "; ".join(reasons) if reasons else "Continue — edge still present",
        "consecutive_wins": consecutive_wins,
        "trades_today": trades_today,
        "wins_today": wins_today,
        "daily_pnl": daily_pnl,
        "max_trades_ceiling": max_trades,
        "locked": False,
        "score": round(score, 1),
    }


def apply_daily_stop(state: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Persist AI daily stop on state when triggered."""
    if decision.get("stop_trading") and not state.get("ai_daily_stop"):
        state["ai_daily_stop"] = True
        state["ai_daily_stop_reason"] = decision.get("reason")
        state["ai_daily_stop_confidence"] = decision.get("confidence", 0)
        state["ai_daily_stop_at"] = datetime.now(IST).isoformat()
    return state


def _no_stop(
    consecutive_wins: int,
    trades_today: int,
    wins_today: int,
    daily_pnl: float,
    max_trades: int,
) -> dict[str, Any]:
    return {
        "stop_trading": False,
        "confidence": 0,
        "reason": "Continue trading — no early-stop trigger yet",
        "consecutive_wins": consecutive_wins,
        "trades_today": trades_today,
        "wins_today": wins_today,
        "daily_pnl": daily_pnl,
        "max_trades_ceiling": max_trades,
        "locked": False,
        "score": 0,
    }
