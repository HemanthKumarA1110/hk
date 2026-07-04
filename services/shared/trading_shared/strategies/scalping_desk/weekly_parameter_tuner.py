"""
Weekly parameter tuner for the scalping desk AI layer.

Deterministic optimisation matching WEEKLY_PARAMETER_TUNER_PROMPT; template
available for LLM extensions via `format_weekly_tuner_prompt`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Any

from trading_shared.strategies.scalping_desk.daily_stop import trading_day_key
from trading_shared.strategies.scalping_desk.expiry_day_handler import to_ist

WEEKLY_PARAMETER_TUNER_PROMPT = """Weekly parameter tuner:
You are the parameter optimisation engine for an AI trading bot. Review the last 5 trading sessions and recommend parameter adjustments.

Last 5 days summary:
- Win rates by day: {WIN_RATES_ARRAY}
- Avg profit per winning trade: {AVG_WIN_PTS}
- Avg loss per losing trade: {AVG_LOSS_PTS}
- Profit factor this week: {PROFIT_FACTOR}
- Sharpe ratio this week: {SHARPE}
- Regime distribution: {REGIME_COUNTS}
- Signals generated vs taken: {SIGNALS_GEN} / {SIGNALS_TAKEN}

Current parameters:
- EMA fast/slow: {EMA_FAST}/{EMA_SLOW}
- RSI period and thresholds: {RSI_PERIOD}, long>{RSI_LONG_THRESH}, short<{RSI_SHORT_THRESH}
- ATR multiplier for SL: {ATR_MULT}
- Volume filter ratio: {VOL_RATIO}

If profit factor < 1.3 or win rate < 52%, suggest parameter tightening.
If profit factor > 2.0 and win rate > 65%, suggest loosening filters for more trades.

Return JSON with reasoning:
{{"ema_fast":0,"ema_slow":0,"rsi_period":0,"rsi_long_thresh":0,"rsi_short_thresh":0,"atr_mult":0,"vol_ratio":0,"confidence":"high|medium|low","reasoning":"<50 words","change_magnitude":"minor|moderate|major"}}"""

DEFAULT_PARAMS = {
    "ema_fast": 9,
    "ema_slow": 21,
    "rsi_period": 14,
    "rsi_long_thresh": 50,
    "rsi_short_thresh": 50,
    "atr_mult": 1.2,
    "vol_ratio": 1.3,
}


def last_n_session_days(n: int = 5, *, anchor: datetime | None = None) -> list[str]:
    """Last N weekday session keys (YYYY-MM-DD), oldest first."""
    now = to_ist(anchor)
    days: list[str] = []
    cursor = now.date()
    while len(days) < n:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor -= timedelta(days=1)
    return list(reversed(days))


def params_from_config(config: dict[str, Any] | None) -> dict[str, float | int]:
    cfg = config or {}
    p = cfg.get("params") or {}
    return {
        "ema_fast": int(p.get("ema_fast") or DEFAULT_PARAMS["ema_fast"]),
        "ema_slow": int(p.get("ema_slow") or DEFAULT_PARAMS["ema_slow"]),
        "rsi_period": int(p.get("rsi_period") or DEFAULT_PARAMS["rsi_period"]),
        "rsi_long_thresh": int(p.get("rsi_call_min") or DEFAULT_PARAMS["rsi_long_thresh"]),
        "rsi_short_thresh": int(p.get("rsi_put_max") or DEFAULT_PARAMS["rsi_short_thresh"]),
        "atr_mult": float(p.get("stop_atr_mult") or DEFAULT_PARAMS["atr_mult"]),
        "vol_ratio": float(p.get("volume_spike_ratio") or DEFAULT_PARAMS["vol_ratio"]),
    }


def config_patch_from_tuning(tuning: dict[str, Any]) -> dict[str, Any]:
    """Map tuner output onto desk `params` keys."""
    return {
        "ema_fast": tuning.get("ema_fast"),
        "ema_slow": tuning.get("ema_slow"),
        "rsi_period": tuning.get("rsi_period"),
        "rsi_call_min": tuning.get("rsi_long_thresh"),
        "rsi_put_max": tuning.get("rsi_short_thresh"),
        "stop_atr_mult": tuning.get("atr_mult"),
        "volume_spike_ratio": tuning.get("vol_ratio"),
    }


def _trade_day(trade: dict[str, Any]) -> str | None:
    ts = trade.get("timestamp") or trade.get("entry_time")
    if not ts:
        return None
    try:
        return to_ist(ts).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return str(ts)[:10] if ts else None


def _trade_pnl_pts(trade: dict[str, Any]) -> float:
    pnl = float(trade.get("pnl") or 0)
    if pnl != 0:
        lots = max(int(trade.get("lots") or 1), 1)
        lot_size = int((trade.get("indicators") or {}).get("lot_size") or 0)
        if lot_size > 0 and abs(pnl) > 50:
            return pnl / (lots * lot_size)
        return pnl / lots if lots else pnl
    entry = float(trade.get("entry_spot") or (trade.get("indicators") or {}).get("spot") or 0)
    exit_px = float(trade.get("exit") or entry)
    if entry <= 0:
        return 0.0
    st = str(trade.get("signal_type") or "").upper()
    move = exit_px - entry if st == "CALL" else entry - exit_px
    return round(move, 2)


def _regime_from_trade(trade: dict[str, Any]) -> str:
    ai = trade.get("ai") or {}
    sel = trade.get("strategy_selection") or {}
    ctx = sel.get("market_context") or {}
    return str(
        ai.get("regime")
        or ctx.get("scalp_regime")
        or ctx.get("regime")
        or "UNKNOWN"
    ).upper()


def aggregate_weekly_stats(
    *,
    trades: list[dict[str, Any]],
    session_summaries: list[dict[str, Any]] | None = None,
    signal_log: list[dict[str, Any]] | None = None,
    days: int = 5,
    anchor: datetime | None = None,
) -> dict[str, Any]:
    """Build last-N-session metrics from trade history and optional daily summaries."""
    session_days = last_n_session_days(days, anchor=anchor)
    by_day: dict[str, list[dict[str, Any]]] = {d: [] for d in session_days}
    for t in trades:
        day = _trade_day(t)
        if day in by_day:
            by_day[day].append(t)

    win_rates: list[float] = []
    daily_pnls: list[float] = []
    wins_pts: list[float] = []
    losses_pts: list[float] = []
    regime_counts: dict[str, int] = {}
    signals_gen = 0
    signals_taken = 0

    summary_map = {s.get("day"): s for s in (session_summaries or []) if s.get("day")}

    for day in session_days:
        day_trades = by_day[day]
        summary = summary_map.get(day) or {}
        if summary.get("signals_generated") is not None:
            signals_gen += int(summary["signals_generated"])
            signals_taken += int(summary.get("signals_taken") or 0)
        else:
            log_day = [x for x in (signal_log or []) if x.get("day") == day]
            if log_day:
                signals_gen += len(log_day)
                signals_taken += sum(1 for x in log_day if x.get("status") == "approved")
            else:
                signals_taken += len(day_trades)
                signals_gen += max(len(day_trades), int(summary.get("signals_generated") or len(day_trades)))

        if not day_trades:
            win_rates.append(0.0)
            daily_pnls.append(float(summary.get("daily_pnl") or 0))
            continue

        wins = sum(1 for t in day_trades if float(t.get("pnl") or 0) > 0)
        win_rates.append(round(wins / len(day_trades) * 100, 1))
        daily_pnls.append(round(sum(float(t.get("pnl") or 0) for t in day_trades), 2))
        for t in day_trades:
            pts = _trade_pnl_pts(t)
            if pts > 0:
                wins_pts.append(pts)
            elif pts < 0:
                losses_pts.append(abs(pts))
            reg = _regime_from_trade(t)
            regime_counts[reg] = regime_counts.get(reg, 0) + 1

    gross_win = sum(wins_pts) if wins_pts else 0.0
    gross_loss = sum(losses_pts) if losses_pts else 0.0
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else (2.0 if gross_win > 0 else 0.0)

    if len(daily_pnls) > 1 and pstdev(daily_pnls) > 0:
        sharpe = round(mean(daily_pnls) / pstdev(daily_pnls), 2)
    else:
        sharpe = 0.0

    traded_days = sum(1 for d in session_days if by_day[d])
    avg_win_rate = round(mean([wr for wr, d in zip(win_rates, session_days) if by_day[d]]) if traded_days else 0, 1)

    return {
        "session_days": session_days,
        "win_rates_by_day": win_rates,
        "avg_win_pts": round(mean(wins_pts), 2) if wins_pts else 0.0,
        "avg_loss_pts": round(mean(losses_pts), 2) if losses_pts else 0.0,
        "profit_factor": profit_factor,
        "sharpe": sharpe,
        "regime_counts": regime_counts,
        "signals_generated": signals_gen,
        "signals_taken": signals_taken,
        "avg_win_rate": avg_win_rate,
        "trade_count": sum(len(by_day[d]) for d in session_days),
        "daily_pnls": daily_pnls,
    }


def format_weekly_tuner_prompt(
    *,
    stats: dict[str, Any],
    current: dict[str, float | int],
) -> str:
    return WEEKLY_PARAMETER_TUNER_PROMPT.format(
        WIN_RATES_ARRAY=stats.get("win_rates_by_day") or [],
        AVG_WIN_PTS=stats.get("avg_win_pts") or 0,
        AVG_LOSS_PTS=stats.get("avg_loss_pts") or 0,
        PROFIT_FACTOR=stats.get("profit_factor") or 0,
        SHARPE=stats.get("sharpe") or 0,
        REGIME_COUNTS=stats.get("regime_counts") or {},
        SIGNALS_GEN=stats.get("signals_generated") or 0,
        SIGNALS_TAKEN=stats.get("signals_taken") or 0,
        EMA_FAST=current.get("ema_fast"),
        EMA_SLOW=current.get("ema_slow"),
        RSI_PERIOD=current.get("rsi_period"),
        RSI_LONG_THRESH=current.get("rsi_long_thresh"),
        RSI_SHORT_THRESH=current.get("rsi_short_thresh"),
        ATR_MULT=current.get("atr_mult"),
        VOL_RATIO=current.get("vol_ratio"),
    )


def _change_magnitude(current: dict[str, float | int], tuned: dict[str, float | int]) -> str:
    deltas = [
        abs(float(tuned["vol_ratio"]) - float(current["vol_ratio"])),
        abs(float(tuned["atr_mult"]) - float(current["atr_mult"])),
        abs(int(tuned["rsi_long_thresh"]) - int(current["rsi_long_thresh"])),
    ]
    mx = max(deltas)
    if mx >= 0.2:
        return "major"
    if mx >= 0.1:
        return "moderate"
    return "minor"


def tune_weekly_parameters(
    *,
    config: dict[str, Any] | None,
    trades: list[dict[str, Any]],
    session_summaries: list[dict[str, Any]] | None = None,
    signal_log: list[dict[str, Any]] | None = None,
    days: int = 5,
    anchor: datetime | None = None,
) -> dict[str, Any]:
    """
    Recommend parameter adjustments from the last N sessions.
    """
    current = params_from_config(config)
    stats = aggregate_weekly_stats(
        trades=trades,
        session_summaries=session_summaries,
        signal_log=signal_log,
        days=days,
        anchor=anchor,
    )
    prompt = format_weekly_tuner_prompt(stats=stats, current=current)

    pf = float(stats.get("profit_factor") or 0)
    wr = float(stats.get("avg_win_rate") or 0)
    trades_n = int(stats.get("trade_count") or 0)

    tuned = dict(current)
    mode = "hold"
    if pf < 1.3 or wr < 52:
        mode = "tighten"
        tuned["vol_ratio"] = round(min(float(current["vol_ratio"]) + 0.15, 1.6), 2)
        tuned["rsi_long_thresh"] = min(int(current["rsi_long_thresh"]) + 2, 55)
        tuned["rsi_short_thresh"] = max(int(current["rsi_short_thresh"]) - 2, 45)
        tuned["atr_mult"] = round(max(float(current["atr_mult"]) - 0.05, 1.0), 2)
        reasoning = f"Tighten filters — PF {pf} and win rate {wr}% below target."
    elif pf > 2.0 and wr > 65:
        mode = "loosen"
        tuned["vol_ratio"] = round(max(float(current["vol_ratio"]) - 0.1, 1.15), 2)
        tuned["rsi_long_thresh"] = max(int(current["rsi_long_thresh"]) - 2, 48)
        tuned["rsi_short_thresh"] = min(int(current["rsi_short_thresh"]) + 2, 52)
        reasoning = f"Loosen filters — strong week PF {pf}, win rate {wr}%."
    else:
        reasoning = f"Hold params — PF {pf} and win rate {wr}% in acceptable band."

    if trades_n < 5:
        reasoning = f"Low sample ({trades_n} trades) — {reasoning}"

    magnitude = _change_magnitude(current, tuned) if mode != "hold" else "minor"
    confidence = "high" if trades_n >= 12 and mode != "hold" else "medium" if trades_n >= 5 else "low"

    return {
        **{k: tuned[k] for k in DEFAULT_PARAMS},
        "confidence": confidence,
        "reasoning": reasoning[:200],
        "change_magnitude": magnitude,
        "mode": mode,
        "weekly_stats": stats,
        "current_params": current,
        "prompt": prompt,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sessions_reviewed": days,
    }


def build_session_summary(
    *,
    day: str | None = None,
    trades: list[dict[str, Any]],
    signal_log: list[dict[str, Any]] | None = None,
    regime: str = "UNKNOWN",
    daily_pnl: float = 0.0,
) -> dict[str, Any]:
    """Compact per-day row for weekly aggregation."""
    day = day or trading_day_key()
    day_trades = [t for t in trades if _trade_day(t) == day]
    log_day = [x for x in (signal_log or []) if x.get("day") == day]
    signals_generated = len(log_day) if log_day else len(day_trades)
    signals_taken = sum(1 for x in log_day if x.get("status") == "approved") if log_day else len(day_trades)
    wins = sum(1 for t in day_trades if float(t.get("pnl") or 0) > 0)
    return {
        "day": day,
        "trades": len(day_trades),
        "wins": wins,
        "win_rate": round(wins / len(day_trades) * 100, 1) if day_trades else 0.0,
        "daily_pnl": round(daily_pnl, 2),
        "regime": regime,
        "signals_generated": signals_generated,
        "signals_taken": signals_taken,
    }


def save_weekly_tuning(redis_client, user_id: int, instrument_key: str, tuning: dict[str, Any]) -> None:
    key = f"scalping:desk:{user_id}:{instrument_key}:weekly_tuning"
    raw = redis_client.get(key)
    history = json.loads(raw) if raw else []
    history.append(tuning)
    redis_client.setex(key, 86400 * 180, json.dumps(history[-26:]))
