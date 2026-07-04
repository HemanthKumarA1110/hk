"""
Opening-range breakout (ORB) confirmation for Nifty / Bank Nifty scalping.

Deterministic analyst layer matching ORB_BREAKOUT_PROMPT; template available
for LLM extensions via `format_orb_confirmation_prompt`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from trading_shared.strategies.scalping_desk.battle_tested_scalp import (
    _session_orb,
    battle_risk,
    in_battle_session,
)
from trading_shared.strategies.scalping_desk.expiry_day_handler import is_instrument_expiry_day
from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

ORB_BREAKOUT_PROMPT = """ORB breakout confirmation:
The opening range for {INSTRUMENT} today is:
- OR High: {OR_HIGH}
- OR Low: {OR_LOW}
- OR Range: {OR_RANGE} points
- Current price: {CURRENT_PRICE}
- Current time: {TIME}
- Today's market gap: {GAP_PERCENT}%

Determine:
1. Is OR_RANGE tradeable for scalping? (ideal: 40-80 pts for Nifty, 120-200 pts for BankNifty)
2. Has price broken out with conviction (close above/below OR with volume > 1.5x avg)?
3. Is there a fake breakout risk? (gap fill pending, major event in next 30 min?)
4. Recommended entry, SL, and target using 1:2 RRR

Return JSON: {{"or_tradeable":true,"breakout_direction":"up|down|none","fake_risk":"low|medium|high","entry":0,"sl":0,"target":0,"confidence":"high|medium|low"}}"""

OR_RANGE_IDEAL: dict[str, tuple[float, float]] = {
    "nifty50": (40.0, 80.0),
    "banknifty": (120.0, 200.0),
}

VOLUME_BREAKOUT_MIN = 1.5


def _instrument_label(instrument_key: str) -> str:
    return INSTRUMENTS.get(instrument_key, {}).get("label") or instrument_key.upper()


def _format_time(ts: Any = None) -> str:
    from trading_shared.strategies.scalping_desk.battle_tested_scalp import _to_ist

    dt = _to_ist(ts) if ts is not None else datetime.now(
        __import__("zoneinfo").ZoneInfo("Asia/Kolkata")
    )
    return dt.strftime("%H:%M IST") if dt else "—"


def format_orb_confirmation_prompt(
    *,
    instrument_key: str,
    or_high: float,
    or_low: float,
    or_range: float,
    current_price: float,
    time_str: str,
    gap_percent: float,
) -> str:
    return ORB_BREAKOUT_PROMPT.format(
        INSTRUMENT=_instrument_label(instrument_key),
        OR_HIGH=round(or_high, 2),
        OR_LOW=round(or_low, 2),
        OR_RANGE=round(or_range, 2),
        CURRENT_PRICE=round(current_price, 2),
        TIME=time_str,
        GAP_PERCENT=round(gap_percent, 3),
    )


def _or_tradeable(instrument_key: str, or_range: float) -> bool:
    lo, hi = OR_RANGE_IDEAL.get(instrument_key, OR_RANGE_IDEAL["nifty50"])
    return lo <= or_range <= hi


def _range_quality(instrument_key: str, or_range: float) -> str:
    lo, hi = OR_RANGE_IDEAL.get(instrument_key, OR_RANGE_IDEAL["nifty50"])
    if lo <= or_range <= hi:
        return "ideal"
    if or_range < lo:
        return "narrow"
    if or_range > hi * 1.35:
        return "wide"
    return "marginal"


def _gap_fill_risk(
    gap_percent: float,
    current_price: float,
    or_high: float,
    or_low: float,
    prev_close: float | None,
) -> bool:
    if prev_close is None or prev_close <= 0 or abs(gap_percent) < 0.35:
        return False
    fill_zone = prev_close
    inside_or = or_low <= current_price <= or_high
    near_fill = abs(current_price - fill_zone) / prev_close * 100 <= 0.25
    return inside_or or near_fill


def _event_risk_soon(macro: dict[str, Any] | None) -> bool:
    if not macro:
        return False
    if macro.get("event_in_30min") or macro.get("major_event_soon"):
        return True
    regime = str(macro.get("regime") or macro.get("scalp_regime") or "").upper()
    return regime == "EVENT_DRIVEN"


def _breakout_conviction(
    *,
    close: float,
    or_high: float,
    or_low: float,
    vol_ratio: float,
    bar_bullish: bool,
    bar_bearish: bool,
) -> str:
    vol_ok = vol_ratio >= VOLUME_BREAKOUT_MIN
    if close > or_high and vol_ok and bar_bullish:
        return "up"
    if close < or_low and vol_ok and bar_bearish:
        return "down"
    if close > or_high and vol_ok:
        return "up"
    if close < or_low and vol_ok:
        return "down"
    if close > or_high:
        return "up_weak"
    if close < or_low:
        return "down_weak"
    return "none"


def _fake_risk(
    *,
    gap_percent: float,
    current_price: float,
    or_high: float,
    or_low: float,
    prev_close: float | None,
    breakout: str,
    vol_ratio: float,
    instrument_key: str,
    timestamp: Any,
    macro: dict[str, Any] | None,
) -> str:
    risks = 0
    if _gap_fill_risk(gap_percent, current_price, or_high, or_low, prev_close):
        risks += 2
    if _event_risk_soon(macro):
        risks += 2
    if is_instrument_expiry_day(timestamp, instrument_key):
        risks += 1
    if breakout.endswith("_weak"):
        risks += 1
    if vol_ratio < VOLUME_BREAKOUT_MIN and breakout != "none":
        risks += 1
    if abs(gap_percent) >= 1.2:
        risks += 1
    if or_low <= current_price <= or_high and breakout != "none":
        risks += 1

    if risks >= 3:
        return "high"
    if risks >= 1:
        return "medium"
    return "low"


def _rrr_levels(
    direction: str,
    entry: float,
    or_high: float,
    or_low: float,
    instrument_key: str,
) -> tuple[float, float, float]:
    risk_meta = battle_risk(instrument_key)
    max_stop = float(risk_meta.get("stop_pts") or 7)

    if direction == "up":
        sl = round(or_low, 2)
        risk_pts = entry - sl
        if risk_pts > max_stop * 1.5:
            sl = round(entry - max_stop, 2)
            risk_pts = max_stop
        if risk_pts <= 0:
            sl = round(entry - max(max_stop, 1), 2)
            risk_pts = entry - sl
        target = round(entry + 2 * risk_pts, 2)
        return round(entry, 2), sl, target

    if direction == "down":
        sl = round(or_high, 2)
        risk_pts = sl - entry
        if risk_pts > max_stop * 1.5:
            sl = round(entry + max_stop, 2)
            risk_pts = max_stop
        if risk_pts <= 0:
            sl = round(entry + max(max_stop, 1), 2)
            risk_pts = sl - entry
        target = round(entry - 2 * risk_pts, 2)
        return round(entry, 2), sl, target

    return 0.0, 0.0, 0.0


def _confidence(
    *,
    tradeable: bool,
    breakout: str,
    fake_risk: str,
    range_quality: str,
) -> str:
    if not tradeable or breakout in ("none", ""):
        return "low"
    direction = breakout.replace("_weak", "")
    if fake_risk == "high":
        return "low"
    if fake_risk == "medium" or breakout.endswith("_weak") or range_quality == "marginal":
        return "medium"
    if tradeable and direction in ("up", "down") and fake_risk == "low" and range_quality == "ideal":
        return "high"
    return "medium"


def confirm_orb_breakout(
    *,
    instrument_key: str,
    or_high: float,
    or_low: float,
    current_price: float,
    close: float | None = None,
    vol_ratio: float = 1.0,
    gap_percent: float = 0.0,
    timestamp: Any = None,
    prev_close: float | None = None,
    bar_open: float | None = None,
    macro: dict[str, Any] | None = None,
    orb_minutes: int = 15,
) -> dict[str, Any]:
    """Return JSON-shaped ORB confirmation."""
    px = float(current_price)
    c = float(close if close is not None else px)
    or_range = round(or_high - or_low, 2)
    tradeable = _or_tradeable(instrument_key, or_range)
    range_quality = _range_quality(instrument_key, or_range)
    time_str = _format_time(timestamp)

    o = float(bar_open if bar_open is not None else c)
    breakout_raw = _breakout_conviction(
        close=c,
        or_high=or_high,
        or_low=or_low,
        vol_ratio=vol_ratio,
        bar_bullish=c > o,
        bar_bearish=c < o,
    )
    if breakout_raw == "none":
        breakout_direction = "none"
    else:
        breakout_direction = breakout_raw.replace("_weak", "")

    fake = _fake_risk(
        gap_percent=gap_percent,
        current_price=px,
        or_high=or_high,
        or_low=or_low,
        prev_close=prev_close,
        breakout=breakout_raw,
        vol_ratio=vol_ratio,
        instrument_key=instrument_key,
        timestamp=timestamp,
        macro=macro,
    )

    if breakout_direction in ("up", "down") and tradeable and fake != "high":
        entry, sl, target = _rrr_levels(breakout_direction, px, or_high, or_low, instrument_key)
    else:
        entry, sl, target = 0.0, 0.0, 0.0

    conf = _confidence(
        tradeable=tradeable,
        breakout=breakout_raw,
        fake_risk=fake,
        range_quality=range_quality,
    )

    prompt = format_orb_confirmation_prompt(
        instrument_key=instrument_key,
        or_high=or_high,
        or_low=or_low,
        or_range=or_range,
        current_price=px,
        time_str=time_str,
        gap_percent=gap_percent,
    )

    return {
        "or_tradeable": tradeable,
        "or_range": or_range,
        "or_high": round(or_high, 2),
        "or_low": round(or_low, 2),
        "range_quality": range_quality,
        "breakout_direction": breakout_direction if breakout_raw != "none" else "none",
        "breakout_conviction": breakout_raw,
        "fake_risk": fake,
        "entry": entry,
        "sl": sl,
        "target": target,
        "confidence": conf,
        "volume_ratio": round(vol_ratio, 2),
        "gap_percent": round(gap_percent, 3),
        "in_session": in_battle_session(timestamp),
        "prompt": prompt,
    }


def _gap_from_df(df: pd.DataFrame, tick: dict[str, Any] | None) -> tuple[float, float | None]:
    prev_close = None
    gap_pct = 0.0
    if tick:
        prev_close = float(tick.get("close") or tick.get("open") or 0) or None
        ltp = float(tick.get("ltp") or tick.get("open") or 0)
        open_px = float(tick.get("open") or ltp)
        if prev_close and prev_close > 0:
            gap_pct = (open_px - prev_close) / prev_close * 100
        return gap_pct, prev_close

    if df is None or df.empty or "timestamp" not in df.columns:
        return 0.0, None

    frame = df.copy()
    frame["ts"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame = frame.dropna(subset=["ts"])
    if frame.empty:
        return 0.0, None
    day = frame["ts"].iloc[-1].date()
    day_rows = frame.loc[frame["ts"].dt.date == day].sort_values("ts")
    if day_rows.empty:
        return 0.0, None
    open_px = float(day_rows.iloc[0]["open"])
    prev_day = frame.loc[frame["ts"].dt.date < day]
    if not prev_day.empty:
        prev_close = float(prev_day.iloc[-1]["close"])
        gap_pct = (open_px - prev_close) / prev_close * 100 if prev_close else 0.0
    return gap_pct, prev_close


def confirm_orb_from_df(
    instrument_key: str,
    df: pd.DataFrame,
    *,
    spot: float | None = None,
    tick: dict[str, Any] | None = None,
    macro: dict[str, Any] | None = None,
    orb_minutes: int = 15,
) -> dict[str, Any] | None:
    """Build ORB confirmation from intraday candles."""
    if df is None or len(df) < 20:
        return None

    from trading_shared.strategies.scalping_desk.engine import enrich_candles

    data = enrich_candles(df) if "volume_ratio" not in df.columns else df
    orb = _session_orb(data, orb_minutes)
    if not orb:
        return None

    row = data.iloc[-1]
    px = float(spot if spot is not None else row["close"])
    gap_pct, prev_close = _gap_from_df(data, tick)
    macro_ctx = dict(macro or {})
    if not macro_ctx.get("regime") and not macro_ctx.get("scalp_regime"):
        pass

    return confirm_orb_breakout(
        instrument_key=instrument_key,
        or_high=float(orb["high"]),
        or_low=float(orb["low"]),
        current_price=px,
        close=float(row["close"]),
        vol_ratio=float(row.get("volume_ratio") or 1),
        gap_percent=gap_pct,
        timestamp=row.get("timestamp"),
        prev_close=prev_close,
        bar_open=float(row["open"]),
        macro=macro_ctx,
        orb_minutes=orb_minutes,
    )


def orb_confirmation_allows_entry(
    confirmation: dict[str, Any] | None,
    signal_type: str | None = None,
) -> bool:
    """Gate ORB strategy entries on confirmation output."""
    if not confirmation:
        return True
    if not confirmation.get("or_tradeable"):
        return False
    direction = str(confirmation.get("breakout_direction") or "none")
    if direction == "none":
        return False
    if confirmation.get("fake_risk") == "high":
        return False
    if confirmation.get("confidence") == "low":
        return False
    st = str(signal_type or "").upper()
    if st == "CALL" and direction != "up":
        return False
    if st == "PUT" and direction != "down":
        return False
    return True
