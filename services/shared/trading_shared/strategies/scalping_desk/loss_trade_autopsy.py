"""
Loss trade autopsy for the scalping desk AI layer.

Brutally honest root-cause classification on losing trades.
Deterministic logic matching LOSS_TRADE_AUTOPSY_PROMPT; template available
for LLM extensions via `format_loss_autopsy_prompt`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from trading_shared.strategies.scalping_desk.battle_tested_scalp import in_battle_session
from trading_shared.strategies.scalping_desk.eod_self_review import _in_optimal_window, _validation_score, _validation_verdict
from trading_shared.strategies.scalping_desk.entry_signal_validator import signal_type_to_direction
from trading_shared.strategies.scalping_desk.expiry_day_handler import to_ist
from trading_shared.strategies.scalping_desk.market_regime_classifier import regime_allows_signal

LOSS_TRADE_AUTOPSY_PROMPT = """Loss trade autopsy:
Conduct a rapid autopsy on this losing trade. Be brutally honest — identify the real root cause, not surface excuses.

Losing trade details:
- Instrument: {INSTRUMENT}, Direction: {DIRECTION}
- Entry: {ENTRY}, SL hit: {SL}, Loss: {LOSS_PTS} pts
- Signal score at entry: {SCORE}/5
- Regime at entry: {REGIME}
- Time: {TIME}
- Candles held: {CANDLE_COUNT}
- What happened after SL hit: price went to {POST_SL_PRICE} (recovered: {RECOVERED})

Classify the loss into one of these root causes:
A) BAD_SIGNAL — signal was weak, should not have been taken (score < 4)
B) BAD_TIMING — correct direction but entered at wrong candle
C) BAD_RISK — SL was too tight for current ATR
D) CORRECT_PROCESS — good trade, market just stopped out (acceptable loss)
E) REGIME_MISMATCH — traded in wrong market condition

Return:
{{"root_cause":"A|B|C|D|E","description":"<25 words","should_have_skipped":true,"corrective_action":"<20 words","update_blacklist":false}}"""

ROOT_LABELS = {
    "A": "BAD_SIGNAL",
    "B": "BAD_TIMING",
    "C": "BAD_RISK",
    "D": "CORRECT_PROCESS",
    "E": "REGIME_MISMATCH",
}


def format_loss_autopsy_prompt(
    *,
    instrument: str,
    direction: str,
    entry: float,
    sl: float,
    loss_pts: float,
    score: int,
    regime: str,
    time_of_entry: str,
    candle_count: int,
    post_sl_price: float,
    recovered: bool,
) -> str:
    return LOSS_TRADE_AUTOPSY_PROMPT.format(
        INSTRUMENT=instrument,
        DIRECTION=direction.upper(),
        ENTRY=round(entry, 2),
        SL=round(sl, 2),
        LOSS_PTS=round(abs(loss_pts), 2),
        SCORE=score,
        REGIME=regime,
        TIME=time_of_entry,
        CANDLE_COUNT=candle_count,
        POST_SL_PRICE=round(post_sl_price, 2),
        RECOVERED="YES" if recovered else "NO",
    )


def _trade_timestamp(trade: dict[str, Any]) -> datetime | None:
    ts = trade.get("entry_time") or trade.get("timestamp")
    if not ts:
        return None
    try:
        return to_ist(ts)
    except (ValueError, TypeError):
        return None


def _loss_pts(trade: dict[str, Any]) -> float:
    entry_spot = float(trade.get("entry_spot") or (trade.get("indicators") or {}).get("spot") or 0)
    exit_px = float(trade.get("exit") or entry_spot)
    if entry_spot <= 0:
        return abs(float(trade.get("pnl") or 0))
    st = str(trade.get("signal_type") or "").upper()
    move = exit_px - entry_spot if st == "CALL" else entry_spot - exit_px
    return round(abs(move), 2)


def _index_sl(trade: dict[str, Any], entry_spot: float, stop_pts: float, is_long: bool) -> float:
    if is_long:
        return round(entry_spot - stop_pts, 2)
    return round(entry_spot + stop_pts, 2)


def _post_sl_analysis(
    trade: dict[str, Any],
    df: pd.DataFrame | None,
    *,
    entry_spot: float,
    target_pts: float,
    signal_type: str,
) -> tuple[float, bool]:
    """Estimate post-stop excursion using candles from exit bar onward."""
    if df is None or df.empty:
        return entry_spot, False

    bars_held = int(trade.get("bars_held") or 0)
    entry_idx = int(trade.get("entry_index") or max(0, len(df) - bars_held - 1))
    exit_idx = min(len(df) - 1, entry_idx + max(bars_held, 0))
    after = df.iloc[exit_idx:]
    if after.empty:
        return float(df.iloc[-1]["close"]), False

    is_long = str(signal_type).upper() == "CALL"
    if is_long:
        post = float(after["close"].max())
        recovered = post >= entry_spot + target_pts * 0.5
    else:
        post = float(after["close"].min())
        recovered = post <= entry_spot - target_pts * 0.5
    return post, recovered


def _stop_too_tight(trade: dict[str, Any]) -> bool:
    ind = trade.get("indicators") or {}
    stop = float(trade.get("stop_pts") or ind.get("index_stop_pts") or 0)
    atr = float(ind.get("atr") or 0)
    if stop <= 0 or atr <= 0:
        return False
    return stop / atr < 1.05


def _stop_exit(trade: dict[str, Any]) -> bool:
    reason = str(trade.get("exit_reason") or "").lower()
    return any(x in reason for x in ("stop", "trail", "sl"))


def _regime_mismatch(
    trade: dict[str, Any],
    regime: str,
    market_regime: dict[str, Any] | None,
) -> bool:
    regime_upper = str(regime or "").upper()
    direction = signal_type_to_direction(trade.get("signal_type"))
    is_long = direction == "LONG"

    if market_regime and not regime_allows_signal(market_regime, trade.get("signal_type")):
        return True

    if regime_upper == "TRENDING_BULL" and not is_long:
        return True
    if regime_upper == "TRENDING_BEAR" and is_long:
        return True
    if regime_upper in ("EVENT_DRIVEN",):
        return True
    if regime_upper == "RANGE_BOUND":
        strategy = str(trade.get("strategy_id") or (trade.get("indicators") or {}).get("strategy_id") or "")
        if strategy in ("momentum_burst", "ema_crossover_rsi") and not is_long:
            return False
        if strategy in ("momentum_burst", "ema_crossover_rsi") and is_long:
            return False
    return False


def _classify_root_cause(
    *,
    score: int,
    verdict: str,
    regime: str,
    trade: dict[str, Any],
    market_regime: dict[str, Any] | None,
    recovered: bool,
    optimal_timing: bool,
    stop_tight: bool,
    stop_exit: bool,
) -> str:
    if score < 4 or verdict in ("SKIP", "WAIT"):
        return "A"
    if _regime_mismatch(trade, regime, market_regime):
        return "E"
    if not optimal_timing or (recovered and score >= 4):
        return "B"
    if stop_tight and stop_exit:
        return "C"
    return "D"


def _description(root: str, *, score: int, recovered: bool, stop_tight: bool, regime: str) -> str:
    if root == "A":
        return f"Validator score {score}/5 — setup failed checklist; trade should not have fired."
    if root == "B":
        return "Direction was fine but entry candle was early; price recovered after stop." if recovered else "Entry timing was off — outside optimal window or poor candle."
    if root == "C":
        return f"Stop too tight vs ATR ({'ratio <1.05' if stop_tight else 'stop hit'}) — noise stopped you out."
    if root == "E":
        return f"Counter to {regime} regime — strategy fought prevailing market condition."
    return "Process was sound; stop loss did its job on a valid setup."


def _corrective_action(root: str) -> str:
    actions = {
        "A": "Hard-block entries with validator score below 4.",
        "B": "Wait for confirmation candle; avoid chasing breakouts.",
        "C": "Widen SL to at least 1.2× ATR in current vol.",
        "D": "Keep process; accept variance on A+ setups.",
        "E": "Respect regime filter; skip counter-trend scalps.",
    }
    return actions[root]


def autopsy_losing_trade(
    *,
    instrument_key: str,
    trade: dict[str, Any],
    regime: str | None = None,
    df: pd.DataFrame | None = None,
    market_regime: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Classify a closed losing trade into root cause A–E.
    """
    pnl = float(trade.get("pnl") or 0)
    if pnl > 0:
        return {"skipped": True, "reason": "trade was not a loss"}

    ind = trade.get("indicators") or {}
    ai = trade.get("ai") or {}
    direction = signal_type_to_direction(trade.get("signal_type"))
    is_long = direction == "LONG"
    score = _validation_score(trade)
    verdict = _validation_verdict(trade)

    entry_spot = float(trade.get("entry_spot") or ind.get("spot") or trade.get("entry") or 0)
    stop_pts = float(trade.get("stop_pts") or ind.get("index_stop_pts") or 0)
    target_pts = float(trade.get("target_pts") or ind.get("index_target_pts") or stop_pts * 2)
    sl = _index_sl(trade, entry_spot, stop_pts, is_long)
    loss_pts = _loss_pts(trade)
    candle_count = int(trade.get("bars_held") or 0)

    reg = str(
        regime
        or ai.get("regime")
        or (market_regime or {}).get("regime")
        or "UNKNOWN"
    ).upper()

    ts = _trade_timestamp(trade)
    time_of_entry = ts.strftime("%H:%M IST") if ts else "unknown"
    post_sl_price, recovered = _post_sl_analysis(
        trade,
        df,
        entry_spot=entry_spot,
        target_pts=target_pts,
        signal_type=str(trade.get("signal_type") or ""),
    )

    optimal = _in_optimal_window(trade, instrument_key)
    stop_tight = _stop_too_tight(trade)
    stop_exit = _stop_exit(trade)

    root = _classify_root_cause(
        score=score,
        verdict=verdict,
        regime=reg,
        trade=trade,
        market_regime=market_regime,
        recovered=recovered,
        optimal_timing=optimal,
        stop_tight=stop_tight,
        stop_exit=stop_exit,
    )

    should_skip = root in ("A", "E") or (root == "B" and not optimal)
    update_blacklist = root in ("A", "E") and score <= 2

    prompt = format_loss_autopsy_prompt(
        instrument=instrument_key,
        direction=direction,
        entry=entry_spot or float(trade.get("entry") or 0),
        sl=sl,
        loss_pts=loss_pts,
        score=score,
        regime=reg,
        time_of_entry=time_of_entry,
        candle_count=candle_count,
        post_sl_price=post_sl_price,
        recovered=recovered,
    )

    from trading_shared.ai.trade_reasoning import review_closed_trade

    post_review = review_closed_trade(
        trade={
            **trade,
            "entry": entry_spot or trade.get("entry"),
            "stoploss": sl,
            "target": (entry_spot + target_pts) if direction == "LONG" else (entry_spot - target_pts),
        },
        candles_after=df,
    )

    return {
        "root_cause": root,
        "root_label": ROOT_LABELS[root],
        "description": _description(root, score=score, recovered=recovered, stop_tight=stop_tight, regime=reg)[:120],
        "should_have_skipped": should_skip,
        "corrective_action": _corrective_action(root)[:80],
        "update_blacklist": update_blacklist,
        "instrument": instrument_key,
        "direction": direction,
        "entry": round(entry_spot or float(trade.get("entry") or 0), 2),
        "sl": sl,
        "loss_pts": loss_pts,
        "score": score,
        "regime": reg,
        "time": time_of_entry,
        "candles_held": candle_count,
        "post_sl_price": round(post_sl_price, 2),
        "recovered_after_sl": recovered,
        "exit_reason": trade.get("exit_reason"),
        "prompt": prompt,
        "post_trade_review": post_review,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def save_loss_autopsy(redis_client, user_id: int, instrument_key: str, autopsy: dict[str, Any]) -> None:
    key = f"scalping:desk:{user_id}:{instrument_key}:loss_autopsies"
    raw = redis_client.get(key)
    history = json.loads(raw) if raw else []
    history.append(autopsy)
    redis_client.setex(key, 86400 * 180, json.dumps(history[-200:]))

    if autopsy.get("update_blacklist"):
        bl_key = f"scalping:desk:{user_id}:{instrument_key}:setup_blacklist"
        bl_raw = redis_client.get(bl_key)
        blacklist = json.loads(bl_raw) if bl_raw else []
        entry = {
            "root_cause": autopsy.get("root_cause"),
            "regime": autopsy.get("regime"),
            "direction": autopsy.get("direction"),
            "score": autopsy.get("score"),
            "logged_at": autopsy.get("generated_at"),
        }
        blacklist.append(entry)
        redis_client.setex(bl_key, 86400 * 180, json.dumps(blacklist[-100:]))


def load_loss_autopsies(redis_client, user_id: int, instrument_key: str) -> list[dict[str, Any]]:
    key = f"scalping:desk:{user_id}:{instrument_key}:loss_autopsies"
    raw = redis_client.get(key)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []
