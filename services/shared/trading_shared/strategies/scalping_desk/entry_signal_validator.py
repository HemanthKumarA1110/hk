"""
Entry signal validator for Nifty / Bank Nifty scalping.

Deterministic checklist scorer matching ENTRY_SIGNAL_VALIDATOR_PROMPT; template
available for LLM extensions via `format_entry_validator_prompt`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from trading_shared.strategies.scalping_desk.battle_tested_scalp import battle_risk, in_battle_session
from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

ENTRY_SIGNAL_VALIDATOR_PROMPT = """Entry signal validator:
You are a trade signal validator for Nifty/BankNifty scalping. A potential {DIRECTION} entry has been detected at {PRICE} based on {INDICATOR_NAME}.

Validate this signal against the following checklist and return a confidence score:
- EMA alignment (9 > 21 for long, 9 < 21 for short)? {EMA_STATUS}
- RSI({RSI_PERIOD}) in tradeable zone (40-60 neutral = skip)? RSI={RSI_VALUE}
- VWAP position (price above VWAP for long)? {VWAP_STATUS}
- Volume at least 1.2x 20-bar avg? Volume ratio={VOL_RATIO}
- Time window valid (09:20–10:30 or 13:30–14:45 IST)? {TIME_STATUS}

Score each factor 0 or 1. If total score >= 4, output TAKE. If 3, output WAIT. If <3, output SKIP.
Respond in JSON: {{"score":0,"verdict":"TAKE|WAIT|SKIP","weak_factors":[],"entry_price":0,"sl":0,"target":0}}"""

FACTOR_KEYS = ("ema_alignment", "rsi_zone", "vwap_position", "volume", "time_window")


def signal_type_to_direction(signal_type: str | None) -> str:
    st = str(signal_type or "").upper()
    return "LONG" if st == "CALL" else "SHORT"


def format_entry_validator_prompt(
    *,
    direction: str,
    price: float,
    indicator_name: str,
    ema_status: str,
    rsi_period: int,
    rsi_value: float,
    vwap_status: str,
    vol_ratio: float,
    time_status: str,
) -> str:
    return ENTRY_SIGNAL_VALIDATOR_PROMPT.format(
        DIRECTION=direction.upper(),
        PRICE=round(price, 2),
        INDICATOR_NAME=indicator_name,
        EMA_STATUS=ema_status,
        RSI_PERIOD=rsi_period,
        RSI_VALUE=round(rsi_value, 2),
        VWAP_STATUS=vwap_status,
        VOL_RATIO=round(vol_ratio, 2),
        TIME_STATUS=time_status,
    )


def _ema_status(ema9: float, ema21: float, is_long: bool) -> tuple[str, int]:
    if is_long:
        ok = ema9 > ema21
        return (f"9>{'21 ✓' if ok else '21 ✗'} ({ema9:.1f}/{ema21:.1f})", 1 if ok else 0)
    ok = ema9 < ema21
    return (f"9<{'21 ✓' if ok else '21 ✗'} ({ema9:.1f}/{ema21:.1f})", 1 if ok else 0)


def _rsi_status(rsi: float, is_long: bool) -> tuple[str, int]:
    """Align with battle/adaptive strategy RSI bands — avoid blocking valid cross signals."""
    if is_long:
        if 50 <= rsi <= 68:
            return (f"{rsi:.1f} momentum zone ✓", 1)
        if 45 <= rsi <= 72:
            return (f"{rsi:.1f} acceptable band", 1)
        return (f"{rsi:.1f} out of band", 0)
    if 32 <= rsi <= 50:
        return (f"{rsi:.1f} momentum zone ✓", 1)
    if 28 <= rsi <= 55:
        return (f"{rsi:.1f} acceptable band", 1)
    return (f"{rsi:.1f} out of band", 0)


def _vwap_status(spot: float, vwap: float, is_long: bool) -> tuple[str, int]:
    if is_long:
        ok = spot > vwap
        return (f"spot {'above' if ok else 'below'} VWAP ({spot:.1f}/{vwap:.1f})", 1 if ok else 0)
    ok = spot < vwap
    return (f"spot {'below' if ok else 'above'} VWAP ({spot:.1f}/{vwap:.1f})", 1 if ok else 0)


def _volume_status(vol_ratio: float, min_ratio: float = 1.05) -> tuple[str, int]:
    ok = vol_ratio >= min_ratio
    return (f"{vol_ratio:.2f}x {'≥' if ok else '<'} {min_ratio}x", 1 if ok else 0)


def _time_status(ts: Any = None) -> tuple[str, int]:
    ok = in_battle_session(ts)
    return ("in session ✓" if ok else "outside 09:20–10:30 / 13:30–14:45", 1 if ok else 0)


def _verdict_from_score(score: int) -> str:
    if score >= 3:
        return "TAKE"
    if score == 2:
        return "WAIT"
    return "SKIP"


def _index_sl_target(
    instrument_key: str,
    spot: float,
    is_long: bool,
    targets: dict[str, Any] | None,
) -> tuple[float, float]:
    tgt = targets or {}
    stop_pts = float(tgt.get("stop_pts") or battle_risk(instrument_key).get("stop_pts") or 7)
    target_pts = float(tgt.get("target_pts") or battle_risk(instrument_key).get("target_pts") or stop_pts * 2)
    if is_long:
        return round(spot - stop_pts, 2), round(spot + target_pts, 2)
    return round(spot + stop_pts, 2), round(spot - target_pts, 2)


def validate_entry_signal(
    *,
    direction: str,
    price: float,
    indicator_name: str,
    ema9: float,
    ema21: float,
    rsi: float,
    vwap: float,
    vol_ratio: float,
    timestamp: Any = None,
    rsi_period: int = 14,
    volume_min: float = 1.05,
    instrument_key: str = "nifty50",
    targets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Score the five-factor checklist; return JSON-shaped validation result.
    """
    is_long = str(direction).upper() in ("LONG", "CALL", "BUY")
    ema_txt, ema_score = _ema_status(ema9, ema21, is_long)
    rsi_txt, rsi_score = _rsi_status(rsi, is_long)
    vwap_txt, vwap_score = _vwap_status(price, vwap, is_long)
    vol_txt, vol_score = _volume_status(vol_ratio, volume_min)
    time_txt, time_score = _time_status(timestamp)

    scores = {
        "ema_alignment": ema_score,
        "rsi_zone": rsi_score,
        "vwap_position": vwap_score,
        "volume": vol_score,
        "time_window": time_score,
    }
    weak = [k for k, v in scores.items() if v == 0]
    total = sum(scores.values())
    verdict = _verdict_from_score(total)
    sl, target = _index_sl_target(instrument_key, price, is_long, targets)

    prompt = format_entry_validator_prompt(
        direction="LONG" if is_long else "SHORT",
        price=price,
        indicator_name=indicator_name,
        ema_status=ema_txt,
        rsi_period=rsi_period,
        rsi_value=rsi,
        vwap_status=vwap_txt,
        vol_ratio=vol_ratio,
        time_status=time_txt,
    )

    return {
        "score": total,
        "verdict": verdict,
        "weak_factors": weak,
        "entry_price": round(price, 2),
        "sl": sl,
        "target": target,
        "prompt": prompt,
        "factors": scores,
        "direction": "LONG" if is_long else "SHORT",
        "indicator_name": indicator_name,
    }


def validate_from_signal(
    instrument_key: str,
    signal: dict[str, Any],
    *,
    targets: dict[str, Any] | None = None,
    timestamp: Any = None,
    volume_min: float = 1.05,
) -> dict[str, Any]:
    """Build validator inputs from a desk signal dict."""
    ind = signal.get("indicators") or {}
    spot = float(ind.get("spot") or signal.get("entry") or 0)
    strategy_id = signal.get("strategy_id") or ind.get("strategy_id") or "unknown"
    label = INSTRUMENTS.get(instrument_key, {}).get("label") or instrument_key
    indicator_name = str(strategy_id).replace("_", " ")

    ts = timestamp or signal.get("timestamp")
    base = validate_entry_signal(
        direction=signal_type_to_direction(signal.get("signal_type")),
        price=spot,
        indicator_name=f"{label} · {indicator_name}",
        ema9=float(ind.get("ema9") or spot),
        ema21=float(ind.get("ema21") or spot),
        rsi=float(ind.get("rsi") or ind.get("rsi14") or 50),
        vwap=float(ind.get("vwap") or spot),
        vol_ratio=float(ind.get("volume_ratio") or 1),
        timestamp=ts,
        volume_min=volume_min,
        instrument_key=instrument_key,
        targets=targets,
    )
    candles = signal.get("recent_candles")
    if candles:
        import pandas as pd

        from trading_shared.ai.trade_reasoning import evaluate_entry_confirmation

        frame = pd.DataFrame(candles)
        confirmation = evaluate_entry_confirmation(
            strategy=indicator_name,
            side=signal_type_to_direction(signal.get("signal_type")),
            entry=spot,
            stop=base["sl"],
            target=base["target"],
            candles=frame,
            timeframe=str(signal.get("timeframe") or "1m"),
            rsi=float(ind.get("rsi") or ind.get("rsi14") or 50),
            atr=float(ind.get("atr") or 0) or None,
            vwap=float(ind.get("vwap") or spot),
            volume_ratio=float(ind.get("volume_ratio") or 1),
            index_trend=(signal.get("metadata") or {}).get("index_trend"),
            sector_trend=(signal.get("metadata") or {}).get("sector_trend"),
        )
        base["entry_confirmation"] = confirmation
        # Only veto a passing checklist when multi-factor score is clearly weak
        if (
            confirmation.get("confidence_score", 100) < 28
            and base.get("verdict") == "TAKE"
        ):
            base["verdict"] = "SKIP"
            base["weak_factors"] = list(base.get("weak_factors") or []) + ["multi_factor_confirmation"]
    return base


def verdict_allows_entry(validation: dict[str, Any] | None) -> bool:
    return bool(validation and validation.get("verdict") == "TAKE")
