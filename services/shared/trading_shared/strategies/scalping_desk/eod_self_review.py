"""
End-of-day self-review / learning module for the scalping desk.

Deterministic analysis matching EOD_SELF_REVIEW_PROMPT; template available for
LLM extensions via `format_eod_review_prompt`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from statistics import mean
from typing import Any

from trading_shared.strategies.scalping_desk.battle_tested_scalp import in_battle_session
from trading_shared.strategies.scalping_desk.daily_stop import trading_day_key
from trading_shared.strategies.scalping_desk.expiry_day_handler import (
    expiry_blocks_new_entries,
    handle_expiry_day,
)

EOD_SELF_REVIEW_PROMPT = """End-of-day self-review:
You are the learning module of an AI trading bot. Review today's trading performance and extract lessons to improve future decisions.

Today's trade log (JSON array of trades):
{TRADE_LOG_JSON}

Today's regime classification: {REGIME}
Market conditions: VIX={VIX}, trend={TREND_DIRECTION}

Analyse:
1. Which trades were taken correctly (signal quality good, execution right)?
2. Which trades were taken with weak signals (score < 4) — were they necessary?
3. Were SLs set too tight or too wide for today's ATR?
4. Was the entry time within the optimal windows?
5. What is the single most important rule the bot violated or could improve?

Output a structured lesson:
{{
  "good_trades": [],
  "avoidable_trades": [],
  "sl_assessment": "too_tight|too_wide|appropriate",
  "timing_compliance_pct": 0,
  "top_lesson": "<40 words",
  "parameter_suggestions": {{
    "rsi_threshold": null,
    "sl_multiplier_adjustment": null,
    "avoid_time_windows": []
  }}
}}"""

BATTLE_WINDOWS = ("09:20-10:30", "13:30-14:45")


def format_eod_review_prompt(
    *,
    trade_log: list[dict[str, Any]],
    regime: str,
    vix: float,
    trend_direction: str,
) -> str:
    return EOD_SELF_REVIEW_PROMPT.format(
        TRADE_LOG_JSON=json.dumps(trade_log, default=str)[:8000],
        REGIME=regime,
        VIX=round(vix, 2),
        TREND_DIRECTION=trend_direction,
    )


def _trade_timestamp(trade: dict[str, Any]) -> str | None:
    return trade.get("timestamp") or trade.get("entry_time")


def _trade_on_day(trade: dict[str, Any], day: str) -> bool:
    ts = _trade_timestamp(trade)
    if not ts:
        return False
    try:
        from trading_shared.strategies.scalping_desk.expiry_day_handler import to_ist

        return to_ist(ts).strftime("%Y-%m-%d") == day
    except (ValueError, TypeError):
        return day in str(ts)


def filter_trades_for_day(trades: list[dict[str, Any]], day: str | None = None) -> list[dict[str, Any]]:
    day = day or trading_day_key()
    return [t for t in trades if _trade_on_day(t, day)]


def _validation_score(trade: dict[str, Any]) -> int:
    ev = trade.get("entry_validation") or (trade.get("ai") or {}).get("entry_validation") or {}
    if ev.get("score") is not None:
        return int(ev["score"])
    return int((trade.get("ai") or {}).get("validation_score") or 0)


def _validation_verdict(trade: dict[str, Any]) -> str:
    ev = trade.get("entry_validation") or (trade.get("ai") or {}).get("entry_validation") or {}
    return str(ev.get("verdict") or (trade.get("ai") or {}).get("validation_verdict") or "")


def _trade_summary(trade: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "index": index,
        "timestamp": _trade_timestamp(trade),
        "signal_type": trade.get("signal_type"),
        "strategy_id": trade.get("strategy_id") or (trade.get("indicators") or {}).get("strategy_id"),
        "pnl": trade.get("pnl"),
        "validation_score": _validation_score(trade),
        "validation_verdict": _validation_verdict(trade) or None,
        "exit_reason": trade.get("exit_reason"),
    }


def _in_optimal_window(trade: dict[str, Any], instrument_key: str) -> bool:
    ts = _trade_timestamp(trade)
    if not in_battle_session(ts):
        return False
    expiry = handle_expiry_day(instrument_key, ts)
    return not expiry_blocks_new_entries(expiry)


def _sl_assessment(trades: list[dict[str, Any]]) -> str:
    if not trades:
        return "appropriate"
    stops: list[float] = []
    atrs: list[float] = []
    stop_exits = 0
    for t in trades:
        ind = t.get("indicators") or {}
        stop = float(t.get("stop_pts") or ind.get("index_stop_pts") or 0)
        atr = float(ind.get("atr") or 0)
        if stop > 0:
            stops.append(stop)
        if atr > 0:
            atrs.append(atr)
        reason = str(t.get("exit_reason") or "").lower()
        if "stop" in reason or reason in ("trail_stop", "sl"):
            stop_exits += 1

    avg_stop = mean(stops) if stops else 0.0
    avg_atr = mean(atrs) if atrs else 0.0
    ratio = avg_stop / avg_atr if avg_atr > 0 else 1.2

    if stop_exits >= max(1, len(trades) // 2) and ratio < 1.05:
        return "too_tight"
    if ratio > 1.75 or (avg_stop > 0 and avg_atr > 0 and avg_stop > avg_atr * 1.6):
        return "too_wide"
    return "appropriate"


def _timing_compliance(trades: list[dict[str, Any]], instrument_key: str) -> float:
    if not trades:
        return 100.0
    ok = sum(1 for t in trades if _in_optimal_window(t, instrument_key))
    return round(ok / len(trades) * 100, 1)


def _parameter_suggestions(
    *,
    trades: list[dict[str, Any]],
    instrument_key: str,
    sl_assessment: str,
    timing_pct: float,
    weak_count: int,
) -> dict[str, Any]:
    rsi_threshold = None
    sl_adj = None
    avoid_windows: list[str] = []

    if sl_assessment == "too_tight":
        sl_adj = 0.15
    elif sl_assessment == "too_wide":
        sl_adj = -0.1

    if weak_count >= 1:
        rsi_threshold = {"call_min": 50, "call_max": 68, "put_min": 32, "put_max": 50}

    if timing_pct < 80:
        avoid_windows.extend(["09:15-09:20", "15:00-15:30"])
    for t in trades:
        ts = _trade_timestamp(t)
        if ts and not in_battle_session(ts):
            avoid_windows.append("outside_battle_session")
            break
    for t in trades:
        ts = _trade_timestamp(t)
        if not ts:
            continue
        exp = handle_expiry_day(instrument_key, ts)
        if exp.get("is_expiry") and exp.get("recommended_window") == "none":
            avoid_windows.append("expiry_before_11:00")
            break

    return {
        "rsi_threshold": rsi_threshold,
        "sl_multiplier_adjustment": sl_adj,
        "avoid_time_windows": sorted(set(avoid_windows)),
    }


def _top_lesson(
    *,
    good: list[dict[str, Any]],
    avoidable: list[dict[str, Any]],
    sl_assessment: str,
    timing_pct: float,
    trades: list[dict[str, Any]],
) -> str:
    if avoidable and all(t.get("validation_score", 0) < 4 for t in avoidable):
        return "Skip entries below validator score 4 — weak signals hurt win rate."
    if timing_pct < 70:
        return "Trade only inside 09:20–10:30 and 13:30–14:45 IST battle windows."
    if sl_assessment == "too_tight":
        return "Stops were tight vs ATR — widen SL multiplier on high-vol days."
    if sl_assessment == "too_wide":
        return "Stops too wide vs ATR — tighten risk or reduce size on choppy days."
    losses = [t for t in trades if float(t.get("pnl") or 0) < 0]
    if len(losses) >= 2 and not good:
        return "No high-quality entries today — waiting for TAKE verdict beats forcing trades."
    if good and not avoidable:
        return "Discipline held — keep validator, session, and regime filters as-is."
    return "Review avoidable trades and enforce validator TAKE before next session."


def run_eod_self_review(
    *,
    instrument_key: str,
    trades: list[dict[str, Any]],
    regime: str = "RANGING",
    vix: float = 15.0,
    trend_direction: str = "neutral",
    day: str | None = None,
) -> dict[str, Any]:
    """
    Analyse today's closed trades and return structured lesson JSON.
    """
    day_trades = filter_trades_for_day(trades, day)
    prompt = format_eod_review_prompt(
        trade_log=[_trade_summary(t, i) for i, t in enumerate(day_trades)],
        regime=regime,
        vix=vix,
        trend_direction=trend_direction,
    )

    good_trades: list[dict[str, Any]] = []
    avoidable_trades: list[dict[str, Any]] = []

    for i, trade in enumerate(day_trades):
        summary = _trade_summary(trade, i)
        score = summary["validation_score"]
        verdict = _validation_verdict(trade)
        pnl = float(trade.get("pnl") or 0)
        optimal = _in_optimal_window(trade, instrument_key)

        weak_signal = score < 4 and verdict not in ("", "TAKE")
        if score == 0 and not verdict:
            weak_signal = False
        quality_ok = score >= 4 and verdict == "TAKE"
        if score == 0 and not verdict and pnl > 0 and optimal:
            quality_ok = True

        if quality_ok and optimal:
            good_trades.append(summary)
        elif weak_signal or not optimal or (pnl < 0 and score > 0 and score < 4):
            avoidable_trades.append({**summary, "reason": _avoid_reason(trade, score, optimal)})

    sl_assessment = _sl_assessment(day_trades)
    timing_pct = _timing_compliance(day_trades, instrument_key)
    params = _parameter_suggestions(
        trades=day_trades,
        instrument_key=instrument_key,
        sl_assessment=sl_assessment,
        timing_pct=timing_pct,
        weak_count=len(avoidable_trades),
    )
    lesson = _top_lesson(
        good=good_trades,
        avoidable=avoidable_trades,
        sl_assessment=sl_assessment,
        timing_pct=timing_pct,
        trades=day_trades,
    )

    return {
        "good_trades": good_trades,
        "avoidable_trades": avoidable_trades,
        "sl_assessment": sl_assessment,
        "timing_compliance_pct": timing_pct,
        "top_lesson": lesson[:160],
        "parameter_suggestions": params,
        "trade_count": len(day_trades),
        "day": day or trading_day_key(),
        "regime": regime,
        "vix": round(vix, 2),
        "trend_direction": trend_direction,
        "prompt": prompt,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _avoid_reason(trade: dict[str, Any], score: int, optimal: bool) -> str:
    parts: list[str] = []
    if score < 4:
        parts.append(f"validator score {score}/5")
    verdict = _validation_verdict(trade)
    if verdict in ("SKIP", "WAIT"):
        parts.append(f"verdict {verdict}")
    if not optimal:
        parts.append("outside optimal window")
    if float(trade.get("pnl") or 0) < 0:
        parts.append("loss")
    return ", ".join(parts) or "weak setup"


def save_eod_review(redis_client, user_id: int, instrument_key: str, review: dict[str, Any]) -> None:
    key = f"scalping:desk:{user_id}:{instrument_key}:eod_reviews"
    raw = redis_client.get(key)
    history = json.loads(raw) if raw else []
    history.append(review)
    redis_client.setex(key, 86400 * 90, json.dumps(history[-60:]))
