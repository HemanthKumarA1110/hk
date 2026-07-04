"""
Trailing stop-loss manager for active scalping trades.

Deterministic implementation of the AI trailing-SL prompt; template available
for LLM extensions via `format_trailing_sl_prompt`.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

TRAILING_SL_PROMPT = """You are managing an active trade. Update the stop loss based on price action.

Active trade:
- Instrument: {INSTRUMENT}
- Direction: {DIRECTION}
- Entry price: {ENTRY}
- Original SL: {ORIGINAL_SL}
- Current SL: {CURRENT_SL}
- Target: {TARGET}
- Current price: {CURRENT_PRICE}
- Current candle: O={O} H={H} L={L} C={C}
- Unrealised P&L: {UNREALISED_PNL} pts

Trailing SL rules:
- Move SL to breakeven once price moves 50% toward target
- After breakeven, trail SL by 1 ATR(14) below each new swing low (long) or above swing high (short)
- Never widen SL
- If price within 5 pts of target, tighten SL to lock in 70% of profit

Return JSON: {{"new_sl":0,"action":"HOLD|TIGHTEN|EXIT","reason":"<15 words"}}"""


def format_trailing_sl_prompt(
    *,
    instrument: str,
    direction: str,
    entry: float,
    original_sl: float,
    current_sl: float,
    target: float,
    current_price: float,
    candle: dict[str, float],
    unrealised_pnl_pts: float,
) -> str:
    return TRAILING_SL_PROMPT.format(
        INSTRUMENT=instrument,
        DIRECTION=direction,
        ENTRY=round(entry, 2),
        ORIGINAL_SL=round(original_sl, 2),
        CURRENT_SL=round(current_sl, 2),
        TARGET=round(target, 2),
        CURRENT_PRICE=round(current_price, 2),
        O=round(candle.get("open", current_price), 2),
        H=round(candle.get("high", current_price), 2),
        L=round(candle.get("low", current_price), 2),
        C=round(candle.get("close", current_price), 2),
        UNREALISED_PNL=round(unrealised_pnl_pts, 2),
    )


def signal_to_direction(signal_type: str) -> str:
    return "LONG" if str(signal_type).upper() == "CALL" else "SHORT"


def _atr14(df: pd.DataFrame) -> float:
    if df.empty:
        return 1.0
    if len(df) == 1:
        return max(float(df.iloc[-1]["high"] - df.iloc[-1]["low"]), 0.5)
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr = pd.concat(
        [
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return float(tr.rolling(14, min_periods=1).mean().iloc[-1])


def _swing_low(df: pd.DataFrame, lookback: int = 8) -> float:
    tail = df.tail(max(lookback, 3))
    return float(tail["low"].min())


def _swing_high(df: pd.DataFrame, lookback: int = 8) -> float:
    tail = df.tail(max(lookback, 3))
    return float(tail["high"].max())


def stop_level_from_pts(entry: float, stop_pts: float, direction: str) -> float:
    if direction == "LONG":
        return entry - stop_pts
    return entry + stop_pts


def stop_pts_from_level(entry: float, stop_level: float, direction: str) -> float:
    if direction == "LONG":
        return max(entry - stop_level, 0.0)
    return max(stop_level - entry, 0.0)


def _signed_move(entry: float, price: float, direction: str) -> float:
    move = price - entry
    return move if direction == "LONG" else -move


def _target_price(entry: float, target_pts: float, direction: str) -> float:
    if direction == "LONG":
        return entry + target_pts
    return entry - target_pts


def _clamp_stop_level(
    proposed: float,
    current_level: float,
    direction: str,
    *,
    allow_above_entry: bool,
) -> float:
    """Never widen — long stops only rise, short stops only fall."""
    if direction == "LONG":
        tightened = max(proposed, current_level)
        if not allow_above_entry:
            return tightened
        return tightened
    tightened = min(proposed, current_level)
    if not allow_above_entry:
        return tightened
    return tightened


def manage_trailing_sl(
    *,
    instrument_key: str,
    trade: dict[str, Any],
    current_price: float,
    df: pd.DataFrame | None = None,
    candle: dict[str, float] | None = None,
) -> dict[str, Any]:
    """
    Update trailing stop for an open index trade.

    Returns JSON-shaped dict with new_sl (price), action, reason, stop_pts,
    trail_floor_move, breakeven_armed, prompt.
    """
    signal_type = str(trade.get("signal_type") or "CALL")
    direction = signal_to_direction(signal_type)
    entry = float(trade.get("entry_spot") or trade.get("indicators", {}).get("spot") or current_price)

    original_pts = float(
        trade.get("original_stop_pts")
        or trade.get("indicators", {}).get("index_stop_pts")
        or trade.get("stop_pts")
        or 0
    )
    current_pts = float(trade.get("stop_pts") or original_pts)
    target_pts = float(trade.get("target_pts") or trade.get("indicators", {}).get("index_target_pts") or 0)

    current_sl_level = float(trade.get("trail_stop_level") or stop_level_from_pts(entry, current_pts, direction))
    original_sl_level = stop_level_from_pts(entry, original_pts, direction)
    target_price = _target_price(entry, target_pts, direction)

    move = _signed_move(entry, current_price, direction)
    unrealised = move

    row = candle or {}
    if not row and df is not None and not df.empty:
        last = df.iloc[-1]
        row = {
            "open": float(last["open"]),
            "high": float(last["high"]),
            "low": float(last["low"]),
            "close": float(last["close"]),
        }
    if not row:
        row = {"open": current_price, "high": current_price, "low": current_price, "close": current_price}

    atr = _atr14(df) if df is not None and not df.empty else max(abs(row["high"] - row["low"]), 0.5)
    breakeven_armed = bool(trade.get("trailing_breakeven"))

    meta = INSTRUMENTS.get(instrument_key, {})
    instrument_label = meta.get("label") or instrument_key.upper()

    prompt = format_trailing_sl_prompt(
        instrument=instrument_label,
        direction=direction,
        entry=entry,
        original_sl=original_sl_level,
        current_sl=current_sl_level,
        target=target_price,
        current_price=current_price,
        candle=row,
        unrealised_pnl_pts=unrealised,
    )

    if target_pts <= 0 or original_pts <= 0:
        return {
            "new_sl": round(current_sl_level, 2),
            "action": "HOLD",
            "reason": "missing target or stop",
            "stop_pts": round(current_pts, 2),
            "trail_floor_move": trade.get("trail_floor_move"),
            "trail_stop_level": round(current_sl_level, 2),
            "breakeven_armed": breakeven_armed,
            "prompt": prompt,
        }

    proposed = current_sl_level
    action = "HOLD"
    reason = "monitoring trail"

    # Rule 4 — lock 70% when within 5 pts of target
    dist_to_target = abs(target_price - current_price)
    if dist_to_target <= 5 and move > 0:
        if direction == "LONG":
            proposed = entry + move * 0.7
        else:
            proposed = entry - move * 0.7
        breakeven_armed = True
        action = "TIGHTEN"
        reason = "lock 70% near target"

    # Rule 1 — breakeven at 50% of target
    elif move >= target_pts * 0.5:
        proposed = entry
        breakeven_armed = True
        if current_sl_level < entry if direction == "LONG" else current_sl_level > entry:
            action = "TIGHTEN"
            reason = "breakeven at 50% target"

    # Rule 2 — ATR trail after breakeven
    if breakeven_armed and df is not None and not df.empty and action == "HOLD":
        if direction == "LONG":
            proposed = _swing_low(df) - atr
            proposed = max(proposed, entry)
        else:
            proposed = _swing_high(df) + atr
            proposed = min(proposed, entry)
        if (direction == "LONG" and proposed > current_sl_level) or (
            direction == "SHORT" and proposed < current_sl_level
        ):
            action = "TIGHTEN"
            reason = "ATR swing trail"

    allow_above = breakeven_armed
    new_sl = _clamp_stop_level(proposed, current_sl_level, direction, allow_above_entry=allow_above)

    # Rule 3 — never widen vs original loss stop on losing side
    if direction == "LONG":
        new_sl = max(new_sl, original_sl_level)
    else:
        new_sl = min(new_sl, original_sl_level)

    # Stop hit → EXIT
    if direction == "LONG" and current_price <= new_sl:
        return {
            "new_sl": round(new_sl, 2),
            "action": "EXIT",
            "reason": "trailing SL hit",
            "stop_pts": round(stop_pts_from_level(entry, new_sl, direction), 2),
            "trail_floor_move": max(new_sl - entry, 0) if new_sl >= entry else None,
            "trail_stop_level": round(new_sl, 2),
            "breakeven_armed": breakeven_armed,
            "prompt": prompt,
        }
    if direction == "SHORT" and current_price >= new_sl:
        return {
            "new_sl": round(new_sl, 2),
            "action": "EXIT",
            "reason": "trailing SL hit",
            "stop_pts": round(stop_pts_from_level(entry, new_sl, direction), 2),
            "trail_floor_move": max(entry - new_sl, 0) if new_sl <= entry else None,
            "trail_stop_level": round(new_sl, 2),
            "breakeven_armed": breakeven_armed,
            "prompt": prompt,
        }

    new_stop_pts = stop_pts_from_level(entry, new_sl, direction)
    if new_sl >= entry and direction == "LONG":
        new_stop_pts = min(new_stop_pts, original_pts)
    elif new_sl <= entry and direction == "SHORT":
        new_stop_pts = min(new_stop_pts, original_pts)

    trail_floor_move = None
    if direction == "LONG" and new_sl >= entry:
        trail_floor_move = round(new_sl - entry, 2)
    elif direction == "SHORT" and new_sl <= entry:
        trail_floor_move = round(entry - new_sl, 2)

    return {
        "new_sl": round(new_sl, 2),
        "action": action,
        "reason": reason[:80],
        "stop_pts": round(new_stop_pts, 2),
        "trail_floor_move": trail_floor_move,
        "trail_stop_level": round(new_sl, 2),
        "breakeven_armed": breakeven_armed,
        "prompt": prompt,
    }


def apply_trailing_to_trade(trade: dict[str, Any], trailing: dict[str, Any]) -> dict[str, Any]:
    """Merge trailing SL output onto an open trade (never widens stop_pts)."""
    original = float(
        trade.get("original_stop_pts")
        or trade.get("indicators", {}).get("index_stop_pts")
        or trade.get("stop_pts")
        or 0
    )
    new_pts = float(trailing.get("stop_pts") or trade.get("stop_pts") or original)
    if original > 0:
        new_pts = min(new_pts, original)

    out = {
        **trade,
        "stop_pts": new_pts,
        "trail_stop_level": trailing.get("trail_stop_level"),
        "trail_floor_move": trailing.get("trail_floor_move"),
        "trailing_breakeven": trailing.get("breakeven_armed", trade.get("trailing_breakeven")),
        "trailing_sl": trailing,
    }
    if "original_stop_pts" not in out and original > 0:
        out["original_stop_pts"] = original
    return out
