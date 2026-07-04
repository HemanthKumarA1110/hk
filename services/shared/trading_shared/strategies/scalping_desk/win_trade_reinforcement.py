"""
Win trade reinforcement for the scalping desk AI layer.

Extracts what worked on winning trades to reinforce future pattern memory.
Deterministic logic matching WIN_TRADE_REINFORCEMENT_PROMPT; template available
for LLM extensions via `format_win_reinforcement_prompt`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from trading_shared.strategies.scalping_desk.eod_self_review import _in_optimal_window, _validation_score
from trading_shared.strategies.scalping_desk.entry_signal_validator import signal_type_to_direction
from trading_shared.strategies.scalping_desk.expiry_day_handler import to_ist
from trading_shared.strategies.scalping_desk.pattern_memory_logger import _infer_candle_pattern, _rsi_zone, _time_window

WIN_TRADE_REINFORCEMENT_PROMPT = """Win trade reinforcement:
Analyse this winning trade and extract what worked so the bot can reinforce these patterns.

Winning trade:
- Instrument: {INSTRUMENT}, Direction: {DIRECTION}
- Entry: {ENTRY}, Exit: {EXIT}, Profit: {PROFIT_PTS} pts
- Signal score at entry: {SCORE}/5
- Regime: {REGIME}, Time: {TIME}
- Was target hit in full or partial exit? {EXIT_TYPE}
- Max adverse excursion (how far against us before winning): {MAE} pts
- Max favourable excursion (how far it ran): {MFE} pts

Extract the win pattern:
1. What was the single strongest factor in this win?
2. Was there a better exit that captured more profit (MFE vs actual exit)?
3. Should the target have been wider or tighter given the day's ATR?
4. Rate the trade quality: A (perfect), B (good), C (lucky)

Return JSON:
{{"trade_grade":"A|B|C","key_success_factor":"<20 words","target_adjustment_suggestion":"wider|tighter|ok","missed_profit_pts":0,"reinforce_pattern":true,"pattern_tags":["tag1","tag2"]}}"""


def format_win_reinforcement_prompt(
    *,
    instrument: str,
    direction: str,
    entry: float,
    exit_price: float,
    profit_pts: float,
    score: int,
    regime: str,
    time_of_entry: str,
    exit_type: str,
    mae: float,
    mfe: float,
) -> str:
    return WIN_TRADE_REINFORCEMENT_PROMPT.format(
        INSTRUMENT=instrument,
        DIRECTION=direction.upper(),
        ENTRY=round(entry, 2),
        EXIT=round(exit_price, 2),
        PROFIT_PTS=round(profit_pts, 2),
        SCORE=score,
        REGIME=regime,
        TIME=time_of_entry,
        EXIT_TYPE=exit_type.upper(),
        MAE=round(mae, 2),
        MFE=round(mfe, 2),
    )


def _trade_timestamp(trade: dict[str, Any]) -> datetime | None:
    ts = trade.get("entry_time") or trade.get("timestamp")
    if not ts:
        return None
    try:
        return to_ist(ts)
    except (ValueError, TypeError):
        return None


def _profit_pts(trade: dict[str, Any]) -> float:
    entry_spot = float(trade.get("entry_spot") or (trade.get("indicators") or {}).get("spot") or 0)
    exit_px = float(trade.get("exit") or entry_spot)
    if entry_spot <= 0:
        return max(float(trade.get("pnl") or 0), 0.0)
    st = str(trade.get("signal_type") or "").upper()
    move = exit_px - entry_spot if st == "CALL" else entry_spot - exit_px
    return round(max(move, 0), 2)


def _mae_mfe(
    trade: dict[str, Any],
    df: pd.DataFrame | None,
    *,
    entry_spot: float,
    signal_type: str,
) -> tuple[float, float]:
    if df is None or df.empty or entry_spot <= 0:
        profit = _profit_pts(trade)
        return 0.0, profit

    bars_held = int(trade.get("bars_held") or 0)
    entry_idx = int(trade.get("entry_index") or max(0, len(df) - bars_held - 1))
    exit_idx = min(len(df) - 1, entry_idx + max(bars_held, 0))
    window = df.iloc[entry_idx : exit_idx + 1]
    if window.empty:
        profit = _profit_pts(trade)
        return 0.0, profit

    is_long = str(signal_type).upper() == "CALL"
    if "high" in window.columns and "low" in window.columns:
        highs = window["high"].astype(float)
        lows = window["low"].astype(float)
    else:
        highs = window["close"].astype(float)
        lows = window["close"].astype(float)

    if is_long:
        mae = max(0.0, entry_spot - float(lows.min()))
        mfe = max(0.0, float(highs.max()) - entry_spot)
    else:
        mae = max(0.0, float(highs.max()) - entry_spot)
        mfe = max(0.0, entry_spot - float(lows.min()))
    return round(mae, 2), round(mfe, 2)


def _exit_type(trade: dict[str, Any], *, profit_pts: float, target_pts: float) -> str:
    reason = str(trade.get("exit_reason") or "").lower()
    if "target" in reason or profit_pts >= target_pts * 0.92:
        return "FULL"
    if any(x in reason for x in ("trail", "ai", "quick", "time", "hold")):
        return "PARTIAL"
    return "FULL" if profit_pts >= target_pts * 0.85 else "PARTIAL"


def _validation_factors(trade: dict[str, Any]) -> dict[str, int]:
    ev = trade.get("entry_validation") or (trade.get("ai") or {}).get("entry_validation") or {}
    factors = ev.get("factors") or {}
    if factors:
        return {str(k): int(v) for k, v in factors.items()}
    weak = ev.get("weak_factors") or []
    labels = {
        "ema_alignment": "EMA alignment",
        "rsi_zone": "RSI zone",
        "vwap_position": "VWAP position",
        "volume": "Volume spike",
        "time_window": "Session timing",
    }
    return {k: 0 if name in weak else 1 for k, name in labels.items()}


def _key_success_factor(
    trade: dict[str, Any],
    *,
    regime: str,
    time_window: str,
    score: int,
) -> str:
    factors = _validation_factors(trade)
    labels = {
        "ema_alignment": "EMA trend alignment",
        "rsi_zone": "RSI momentum zone",
        "vwap_position": "VWAP side confirmation",
        "volume": "Volume expansion",
        "time_window": "Optimal session window",
    }
    best = max(factors.items(), key=lambda x: x[1], default=("time_window", 0))
    if best[1] >= 1:
        return f"{labels.get(best[0], best[0])} in {regime} ({time_window})."
    if score >= 4:
        return f"High-conviction validator score {score}/5 in {regime}."
    strategy = trade.get("strategy_id") or (trade.get("indicators") or {}).get("strategy_id") or "setup"
    return f"{strategy} played out despite mixed checklist."


def _target_adjustment(*, mfe: float, profit_pts: float, target_pts: float, atr: float) -> str:
    if target_pts <= 0:
        return "ok"
    if mfe >= target_pts * 1.25:
        return "wider"
    if mfe <= target_pts * 0.55 and profit_pts >= target_pts * 0.85:
        return "tighter"
    if atr > 0 and target_pts > atr * 2.2:
        return "tighter"
    return "ok"


def _trade_grade(
    *,
    score: int,
    optimal_timing: bool,
    exit_type: str,
    mae: float,
    stop_pts: float,
    missed_profit: float,
    mfe: float,
) -> str:
    if score < 4 or not optimal_timing:
        return "C"
    stress = mae / stop_pts if stop_pts > 0 else 0.0
    capture = (1 - missed_profit / mfe) if mfe > 0 else 1.0
    if score >= 4 and optimal_timing and exit_type == "FULL" and stress <= 0.45 and capture >= 0.75:
        return "A"
    if score >= 4 and stress <= 0.7:
        return "B"
    return "C"


def _pattern_tags(
    trade: dict[str, Any],
    *,
    regime: str,
    time_window: str,
    direction: str,
) -> list[str]:
    ind = trade.get("indicators") or {}
    is_long = direction == "LONG"
    ema9 = float(ind.get("ema9") or 0)
    ema21 = float(ind.get("ema21") or 0)
    rsi = float(ind.get("rsi") or ind.get("rsi14") or 50)
    tags = [
        regime.lower(),
        time_window.replace(":", "").replace("-", "_"),
        direction.lower(),
        _rsi_zone(rsi, is_long),
        _infer_candle_pattern(ind, direction),
    ]
    strategy = trade.get("strategy_id") or ind.get("strategy_id")
    if strategy:
        tags.append(str(strategy))
    if ema9 and ema21:
        tags.append("ema_aligned" if (ema9 > ema21) == is_long else "ema_mixed")
    vol = float(ind.get("volume_ratio") or 0)
    if vol >= 1.2:
        tags.append("volume_spike")
    return sorted(set(t for t in tags if t and t != "unknown"))[:8]


def reinforce_winning_trade(
    *,
    instrument_key: str,
    trade: dict[str, Any],
    regime: str | None = None,
    df: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Analyse a closed winning trade and return reinforcement JSON."""
    pnl = float(trade.get("pnl") or 0)
    profit_pts = _profit_pts(trade)
    if pnl <= 0 and profit_pts <= 0:
        return {"skipped": True, "reason": "trade was not a win"}

    ind = trade.get("indicators") or {}
    ai = trade.get("ai") or {}
    direction = signal_type_to_direction(trade.get("signal_type"))
    score = _validation_score(trade)
    entry_spot = float(trade.get("entry_spot") or ind.get("spot") or trade.get("entry") or 0)
    exit_px = float(trade.get("exit") or entry_spot)
    target_pts = float(trade.get("target_pts") or ind.get("index_target_pts") or 0)
    stop_pts = float(trade.get("stop_pts") or ind.get("index_stop_pts") or 0)
    atr = float(ind.get("atr") or 0)

    reg = str(regime or ai.get("regime") or "UNKNOWN").upper()
    ts = _trade_timestamp(trade)
    time_of_entry = ts.strftime("%H:%M IST") if ts else "unknown"
    time_window = _time_window(ts)

    mae, mfe = _mae_mfe(trade, df, entry_spot=entry_spot, signal_type=str(trade.get("signal_type") or ""))
    mfe = max(mfe, profit_pts)
    missed = round(max(0.0, mfe - profit_pts), 2)
    exit_type = _exit_type(trade, profit_pts=profit_pts, target_pts=target_pts)
    optimal = _in_optimal_window(trade, instrument_key)

    target_adj = _target_adjustment(
        mfe=mfe,
        profit_pts=profit_pts,
        target_pts=target_pts,
        atr=atr,
    )
    grade = _trade_grade(
        score=score,
        optimal_timing=optimal,
        exit_type=exit_type,
        mae=mae,
        stop_pts=stop_pts,
        missed_profit=missed,
        mfe=mfe,
    )
    reinforce = grade in ("A", "B") and score >= 4

    prompt = format_win_reinforcement_prompt(
        instrument=instrument_key,
        direction=direction,
        entry=entry_spot or float(trade.get("entry") or 0),
        exit_price=exit_px,
        profit_pts=profit_pts,
        score=score,
        regime=reg,
        time_of_entry=time_of_entry,
        exit_type=exit_type,
        mae=mae,
        mfe=mfe,
    )

    return {
        "trade_grade": grade,
        "key_success_factor": _key_success_factor(trade, regime=reg, time_window=time_window, score=score)[:120],
        "target_adjustment_suggestion": target_adj,
        "missed_profit_pts": missed,
        "reinforce_pattern": reinforce,
        "pattern_tags": _pattern_tags(trade, regime=reg, time_window=time_window, direction=direction),
        "instrument": instrument_key,
        "direction": direction,
        "entry": round(entry_spot or float(trade.get("entry") or 0), 2),
        "exit": round(exit_px, 2),
        "profit_pts": profit_pts,
        "score": score,
        "regime": reg,
        "time": time_of_entry,
        "exit_type": exit_type,
        "mae_pts": mae,
        "mfe_pts": mfe,
        "prompt": prompt,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def save_win_reinforcement(redis_client, user_id: int, instrument_key: str, reinforcement: dict[str, Any]) -> None:
    key = f"scalping:desk:{user_id}:{instrument_key}:win_reinforcements"
    raw = redis_client.get(key)
    history = json.loads(raw) if raw else []
    history.append(reinforcement)
    redis_client.setex(key, 86400 * 365, json.dumps(history[-500:]))

    if reinforcement.get("reinforce_pattern"):
        tag_key = f"scalping:desk:{user_id}:{instrument_key}:reinforced_tags"
        tag_raw = redis_client.get(tag_key)
        tags = json.loads(tag_raw) if tag_raw else []
        tags.append(
            {
                "tags": reinforcement.get("pattern_tags") or [],
                "grade": reinforcement.get("trade_grade"),
                "logged_at": reinforcement.get("generated_at"),
            }
        )
        redis_client.setex(tag_key, 86400 * 365, json.dumps(tags[-200:]))


def load_win_reinforcements(redis_client, user_id: int, instrument_key: str) -> list[dict[str, Any]]:
    key = f"scalping:desk:{user_id}:{instrument_key}:win_reinforcements"
    raw = redis_client.get(key)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []
