"""
Pattern memory logger for the scalping desk AI layer.

Logs completed trades as reusable setup fingerprints for future recognition.
Deterministic logic matching PATTERN_MEMORY_LOGGER_PROMPT; template available
for LLM extensions via `format_pattern_memory_prompt`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from trading_shared.strategies.scalping_desk.battle_tested_scalp import in_battle_session
from trading_shared.strategies.scalping_desk.entry_signal_validator import signal_type_to_direction
from trading_shared.strategies.scalping_desk.expiry_day_handler import to_ist

PATTERN_MEMORY_LOGGER_PROMPT = """Pattern memory logger:
Log this completed trade as a pattern in the bot memory database. This will be used to recognise similar setups in the future.

Trade result:
- Instrument: {INSTRUMENT}
- Date/time: {DATETIME}
- Direction: {DIRECTION}
- Entry: {ENTRY}, SL: {SL}, Target: {TARGET}
- Exit: {EXIT_PRICE}, Result: {RESULT}, P&L: {PNL} pts
- Regime at entry: {REGIME}
- Signal indicators: EMA_STATUS={EMA}, RSI={RSI}, VWAP={VWAP}, VOL_RATIO={VOL}
- Candle pattern at entry: {CANDLE_PATTERN}
- Time of entry: {TIME}

Summarise this as a reusable pattern entry:
{{"pattern_id":"auto-generate hash","setup_fingerprint":"<describe the setup in 20 words>","conditions":{{"regime":"","ema_aligned":true,"rsi_zone":"","above_vwap":true,"candle":"","time_window":""}},"outcome":"win|loss","edge_score":0,"frequency_tag":"common|rare","recommendation":"take|avoid|take_with_reduced_size"}}"""

MATCH_KEYS = ("regime", "ema_aligned", "rsi_zone", "above_vwap", "candle", "time_window")


def format_pattern_memory_prompt(
    *,
    instrument: str,
    dt: str,
    direction: str,
    entry: float,
    sl: float,
    target: float,
    exit_price: float,
    result: str,
    pnl_pts: float,
    regime: str,
    ema: str,
    rsi: float,
    vwap: str,
    vol: float,
    candle_pattern: str,
    time_of_entry: str,
) -> str:
    return PATTERN_MEMORY_LOGGER_PROMPT.format(
        INSTRUMENT=instrument,
        DATETIME=dt,
        DIRECTION=direction.upper(),
        ENTRY=round(entry, 2),
        SL=round(sl, 2),
        TARGET=round(target, 2),
        EXIT_PRICE=round(exit_price, 2),
        RESULT=result.upper(),
        PNL=round(pnl_pts, 2),
        REGIME=regime,
        EMA=ema,
        RSI=round(rsi, 2),
        VWAP=vwap,
        VOL=round(vol, 2),
        CANDLE_PATTERN=candle_pattern,
        TIME=time_of_entry,
    )


def _trade_timestamp(trade: dict[str, Any]) -> datetime | None:
    ts = trade.get("entry_time") or trade.get("timestamp")
    if not ts:
        return None
    try:
        return to_ist(ts)
    except (ValueError, TypeError):
        return None


def _pnl_pts(trade: dict[str, Any]) -> float:
    pnl = float(trade.get("pnl") or 0)
    if pnl != 0:
        entry_spot = float(trade.get("entry_spot") or (trade.get("indicators") or {}).get("spot") or 0)
        exit_px = float(trade.get("exit") or entry_spot)
        if entry_spot > 0 and abs(exit_px - entry_spot) > 0:
            st = str(trade.get("signal_type") or "").upper()
            move = exit_px - entry_spot if st == "CALL" else entry_spot - exit_px
            return round(move, 2)
        lots = max(int(trade.get("lots") or 1), 1)
        lot_size = int((trade.get("indicators") or {}).get("lot_size") or 0)
        if lot_size > 0 and abs(pnl) > 50:
            return round(pnl / (lots * lot_size), 2)
    entry_spot = float(trade.get("entry_spot") or (trade.get("indicators") or {}).get("spot") or 0)
    exit_px = float(trade.get("exit") or entry_spot)
    if entry_spot <= 0:
        return 0.0
    st = str(trade.get("signal_type") or "").upper()
    move = exit_px - entry_spot if st == "CALL" else entry_spot - exit_px
    return round(move, 2)


def _time_window(ts: datetime | None) -> str:
    if ts is None:
        return "unknown"
    minutes = ts.hour * 60 + ts.minute
    if 9 * 60 + 20 <= minutes <= 10 * 60 + 30:
        return "09:20-10:30"
    if 13 * 60 + 30 <= minutes <= 14 * 60 + 45:
        return "13:30-14:45"
    if in_battle_session(ts):
        return "session"
    return "off_session"


def _rsi_zone(rsi: float, is_long: bool) -> str:
    if 40 <= rsi <= 60:
        return "neutral"
    if is_long:
        if rsi > 72:
            return "overbought"
        if rsi > 60:
            return "bullish"
        return "weak_long"
    if rsi < 28:
        return "oversold"
    if rsi < 40:
        return "bearish"
    return "weak_short"


def _infer_candle_pattern(ind: dict[str, Any], direction: str) -> str:
    explicit = ind.get("candle_pattern") or ind.get("candle")
    if explicit:
        return str(explicit).lower().replace(" ", "_")

    o = ind.get("open")
    h = ind.get("high")
    low = ind.get("low")
    c = ind.get("close") or ind.get("spot")
    if None not in (o, h, low, c):
        o, h, low, c = float(o), float(h), float(low), float(c)
        body = abs(c - o)
        rng = max(h - low, 0.01)
        upper = h - max(o, c)
        lower = min(o, c) - low
        if body / rng < 0.12:
            return "doji"
        if lower > body * 2 and upper < body * 0.5:
            return "hammer" if direction in ("LONG", "CALL") else "shooting_star"
        if upper > body * 2 and lower < body * 0.5:
            return "shooting_star" if direction in ("LONG", "CALL") else "hammer"
        if c > o and body / rng > 0.55:
            return "bullish_marubozu"
        if c < o and body / rng > 0.55:
            return "bearish_marubozu"
        return "bullish" if c > o else "bearish"

    conditions = ind.get("conditions_met") or []
    if isinstance(conditions, list):
        for tag in ("orb_breakout", "ema_cross", "vwap_bounce", "momentum_burst"):
            if tag in conditions:
                return tag
    return "unknown"


def _ema_status_text(ema9: float, ema21: float, is_long: bool) -> str:
    if is_long:
        return f"9>{'21' if ema9 > ema21 else '21'} ({ema9:.1f}/{ema21:.1f})"
    return f"9<{'21' if ema9 < ema21 else '21'} ({ema9:.1f}/{ema21:.1f})"


def _vwap_status_text(spot: float, vwap: float, is_long: bool) -> str:
    side = "above" if spot > vwap else "below"
    if not is_long:
        side = "below" if spot < vwap else "above"
    return f"spot {side} VWAP ({spot:.1f}/{vwap:.1f})"


def _build_conditions(
    *,
    regime: str,
    ema9: float,
    ema21: float,
    rsi: float,
    spot: float,
    vwap: float,
    candle: str,
    time_window: str,
    is_long: bool,
) -> dict[str, Any]:
    return {
        "regime": str(regime or "UNKNOWN").upper(),
        "ema_aligned": ema9 > ema21 if is_long else ema9 < ema21,
        "rsi_zone": _rsi_zone(rsi, is_long),
        "above_vwap": spot > vwap if is_long else spot < vwap,
        "candle": candle,
        "time_window": time_window,
    }


def _pattern_id(instrument: str, direction: str, conditions: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "instrument": instrument,
            "direction": direction.upper(),
            "conditions": {k: conditions.get(k) for k in MATCH_KEYS},
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _setup_fingerprint(
    *,
    instrument: str,
    direction: str,
    conditions: dict[str, Any],
    strategy_id: str,
) -> str:
    ema = "aligned" if conditions.get("ema_aligned") else "mixed"
    vwap = "above VWAP" if conditions.get("above_vwap") else "below VWAP"
    parts = [
        instrument,
        direction.upper(),
        conditions.get("regime", ""),
        f"EMA {ema}",
        f"RSI {conditions.get('rsi_zone')}",
        vwap,
        str(conditions.get("candle")),
        str(conditions.get("time_window")),
        strategy_id or "scalp",
    ]
    text = " · ".join(p for p in parts if p)
    words = text.split()
    return " ".join(words[:20])


def _edge_score(*, outcome: str, validation_score: int, pnl_pts: float) -> int:
    base = 50
    if outcome == "win":
        base += 25 + min(int(abs(pnl_pts)), 20)
    else:
        base -= 25 + min(int(abs(pnl_pts) / 2), 20)
    if validation_score >= 4:
        base += 10
    elif validation_score <= 2:
        base -= 15
    return max(0, min(100, base))


def _frequency_tag(pattern_id: str, history: list[dict[str, Any]] | None) -> str:
    count = sum(1 for p in (history or []) if p.get("pattern_id") == pattern_id)
    return "common" if count >= 2 else "rare"


def _recommendation(*, outcome: str, edge_score: int, validation_score: int, similar: list[dict[str, Any]]) -> str:
    if similar:
        wins = sum(1 for p in similar if p.get("outcome") == "win")
        losses = len(similar) - wins
        if losses >= 2 and wins == 0:
            return "avoid"
        if wins >= 2 and losses == 0:
            return "take"
        if wins > losses and edge_score >= 55:
            return "take"
        if losses > wins:
            return "take_with_reduced_size" if validation_score >= 4 else "avoid"

    if outcome == "loss" and validation_score <= 2:
        return "avoid"
    if outcome == "loss" and validation_score >= 4:
        return "take_with_reduced_size"
    if outcome == "win" and edge_score >= 65:
        return "take"
    if outcome == "win":
        return "take_with_reduced_size"
    return "avoid"


def find_similar_patterns(
    patterns: list[dict[str, Any]],
    conditions: dict[str, Any],
    *,
    direction: str | None = None,
    min_match: int = 4,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return stored patterns whose conditions overlap the query setup."""
    matches: list[tuple[int, dict[str, Any]]] = []
    for pattern in patterns:
        if direction and str(pattern.get("direction", "")).upper() != direction.upper():
            continue
        cond = pattern.get("conditions") or {}
        score = sum(1 for key in MATCH_KEYS if cond.get(key) == conditions.get(key))
        if score >= min_match:
            matches.append((score, pattern))
    matches.sort(key=lambda x: (-x[0], x[1].get("logged_at", "")))
    return [p for _, p in matches[:limit]]


def log_trade_pattern(
    *,
    instrument_key: str,
    trade: dict[str, Any],
    regime: str | None = None,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a pattern memory entry from a closed trade record."""
    ind = trade.get("indicators") or {}
    ai = trade.get("ai") or {}
    sel = trade.get("strategy_selection") or {}
    ctx = sel.get("market_context") or {}

    direction = signal_type_to_direction(trade.get("signal_type"))
    is_long = direction == "LONG"
    ts = _trade_timestamp(trade)
    dt_str = ts.isoformat() if ts else str(trade.get("timestamp") or "")

    spot = float(trade.get("entry_spot") or ind.get("spot") or trade.get("entry") or 0)
    ema9 = float(ind.get("ema9") or 0)
    ema21 = float(ind.get("ema21") or 0)
    rsi = float(ind.get("rsi") or ind.get("rsi14") or 50)
    vwap = float(ind.get("vwap") or spot)
    vol = float(ind.get("volume_ratio") or 1)

    entry = float(trade.get("entry") or spot)
    stop_pts = float(trade.get("stop_pts") or ind.get("index_stop_pts") or 0)
    target_pts = float(trade.get("target_pts") or ind.get("index_target_pts") or stop_pts * 2)
    if is_long:
        sl = round(spot - stop_pts, 2) if spot else round(entry - stop_pts, 2)
        target = round(spot + target_pts, 2) if spot else round(entry + target_pts, 2)
    else:
        sl = round(spot + stop_pts, 2) if spot else round(entry + stop_pts, 2)
        target = round(spot - target_pts, 2) if spot else round(entry - target_pts, 2)

    exit_px = float(trade.get("exit") or spot)
    pnl_pts = _pnl_pts(trade)
    outcome = "win" if float(trade.get("pnl") or 0) > 0 or pnl_pts > 0 else "loss"

    reg = str(
        regime
        or ai.get("regime")
        or ctx.get("scalp_regime")
        or ctx.get("regime")
        or "UNKNOWN"
    ).upper()
    time_window = _time_window(ts)
    candle = _infer_candle_pattern({**ind, "conditions_met": trade.get("conditions_met")}, direction)
    conditions = _build_conditions(
        regime=reg,
        ema9=ema9,
        ema21=ema21,
        rsi=rsi,
        spot=spot,
        vwap=vwap,
        candle=candle,
        time_window=time_window,
        is_long=is_long,
    )

    strategy_id = str(trade.get("strategy_id") or ind.get("strategy_id") or "")
    pattern_id = _pattern_id(instrument_key, direction, conditions)
    validation_score = int((trade.get("entry_validation") or {}).get("score") or 0)
    similar = find_similar_patterns(history or [], conditions, direction=direction, min_match=4)
    edge = _edge_score(outcome=outcome, validation_score=validation_score, pnl_pts=pnl_pts)
    freq = _frequency_tag(pattern_id, history)
    rec = _recommendation(
        outcome=outcome,
        edge_score=edge,
        validation_score=validation_score,
        similar=similar,
    )

    ema_txt = _ema_status_text(ema9, ema21, is_long)
    vwap_txt = _vwap_status_text(spot, vwap, is_long)
    time_of_entry = ts.strftime("%H:%M IST") if ts else "unknown"

    prompt = format_pattern_memory_prompt(
        instrument=instrument_key,
        dt=dt_str,
        direction=direction,
        entry=entry,
        sl=sl,
        target=target,
        exit_price=exit_px,
        result=outcome.upper(),
        pnl_pts=pnl_pts,
        regime=reg,
        ema=ema_txt,
        rsi=rsi,
        vwap=vwap_txt,
        vol=vol,
        candle_pattern=candle,
        time_of_entry=time_of_entry,
    )

    return {
        "pattern_id": pattern_id,
        "instrument": instrument_key,
        "direction": direction,
        "datetime": dt_str,
        "setup_fingerprint": _setup_fingerprint(
            instrument=instrument_key,
            direction=direction,
            conditions=conditions,
            strategy_id=strategy_id,
        ),
        "conditions": conditions,
        "outcome": outcome,
        "edge_score": edge,
        "frequency_tag": freq,
        "recommendation": rec,
        "pnl_pts": pnl_pts,
        "validation_score": validation_score,
        "strategy_id": strategy_id,
        "similar_hits": len(similar),
        "prompt": prompt,
        "logged_at": datetime.now(timezone.utc).isoformat(),
    }


def match_signal_to_memory(
    signal: dict[str, Any],
    history: list[dict[str, Any]] | None,
    *,
    regime: str | None = None,
) -> dict[str, Any]:
    """Check stored patterns against a live/pending signal setup."""
    ind = signal.get("indicators") or {}
    direction = signal_type_to_direction(signal.get("signal_type"))
    is_long = direction == "LONG"
    ts = _trade_timestamp(signal)
    spot = float(ind.get("spot") or signal.get("entry") or 0)
    conditions = _build_conditions(
        regime=str(regime or "UNKNOWN"),
        ema9=float(ind.get("ema9") or 0),
        ema21=float(ind.get("ema21") or 0),
        rsi=float(ind.get("rsi") or ind.get("rsi14") or 50),
        spot=spot,
        vwap=float(ind.get("vwap") or spot),
        candle=_infer_candle_pattern(ind, direction),
        time_window=_time_window(ts),
        is_long=is_long,
    )
    similar = find_similar_patterns(history or [], conditions, direction=direction, min_match=4)
    if not similar:
        return {"matched": False, "similar_count": 0, "recommendation": "take", "avg_edge": 0}

    avg_edge = round(sum(int(p.get("edge_score") or 0) for p in similar) / len(similar), 1)
    wins = sum(1 for p in similar if p.get("outcome") == "win")
    rec = "take" if wins >= len(similar) / 2 else "take_with_reduced_size" if wins else "avoid"
    return {
        "matched": True,
        "similar_count": len(similar),
        "pattern_ids": [p.get("pattern_id") for p in similar[:3]],
        "recommendation": rec,
        "avg_edge": avg_edge,
        "win_rate_pct": round(wins / len(similar) * 100, 1),
        "conditions": conditions,
    }


def save_pattern_memory(redis_client, user_id: int, instrument_key: str, pattern: dict[str, Any]) -> None:
    key = f"scalping:desk:{user_id}:{instrument_key}:pattern_memory"
    raw = redis_client.get(key)
    history = json.loads(raw) if raw else []
    history.append(pattern)
    redis_client.setex(key, 86400 * 365, json.dumps(history[-500:]))


def load_pattern_memory(redis_client, user_id: int, instrument_key: str) -> list[dict[str, Any]]:
    key = f"scalping:desk:{user_id}:{instrument_key}:pattern_memory"
    raw = redis_client.get(key)
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []
