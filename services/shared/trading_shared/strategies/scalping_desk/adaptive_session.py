"""
Adaptive scalping session gate — market conditions instead of fixed time windows.

Replaces battle-tested fixed windows (09:20–10:30 / 13:30–14:45) with:
  - ATR above threshold
  - Volume > 20-period average
  - ADX > 25 (trend strength)
  - No major economic/news event in the next 15 minutes
  - Spread within acceptable limits
  - 15m trend aligns with trade direction (when signal_type is known)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pandas as pd

IST = __import__("zoneinfo").ZoneInfo("Asia/Kolkata")

MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)
SKIP_OPEN_MINUTES = 5
SKIP_CLOSE_MINUTES = 15

INSTRUMENT_THRESHOLDS: dict[str, dict[str, float | int]] = {
    "nifty50": {
        "min_atr_pts": 8.0,
        "min_atr_pct": 0.025,
        "atr_median_mult": 0.7,
        "min_volume_ratio": 1.0,
        "min_adx": 25.0,
        "max_spread_bps": 6.0,
        "max_range_spread_pct": 0.06,
        "news_block_minutes": 15,
    },
    "banknifty": {
        "min_atr_pts": 35.0,
        "min_atr_pct": 0.03,
        "atr_median_mult": 0.7,
        "min_volume_ratio": 1.0,
        "min_adx": 25.0,
        "max_spread_bps": 8.0,
        "max_range_spread_pct": 0.05,
        "news_block_minutes": 15,
    },
}

HIGH_IMPACT_LABELS = frozenset({"high", "major", "critical", "3"})


def _to_ist(ts: Any = None) -> datetime:
    if ts is None:
        return datetime.now(IST)
    dt = pd.to_datetime(ts, errors="coerce")
    if pd.isna(dt):
        return datetime.now(IST)
    if dt.tzinfo is None:
        return dt.to_pydatetime().replace(tzinfo=IST)
    return dt.astimezone(IST)


def in_market_hours(ts: Any = None) -> bool:
    """NSE cash session with open/close buffers — not fixed scalp windows."""
    now = _to_ist(ts)
    if now.weekday() >= 5:
        return False
    minutes = now.hour * 60 + now.minute
    open_min = MARKET_OPEN[0] * 60 + MARKET_OPEN[1] + SKIP_OPEN_MINUTES
    close_cutoff = MARKET_CLOSE[0] * 60 + MARKET_CLOSE[1] - SKIP_CLOSE_MINUTES
    return open_min <= minutes < close_cutoff


def _thresholds(instrument_key: str) -> dict[str, float | int]:
    return INSTRUMENT_THRESHOLDS.get(instrument_key, INSTRUMENT_THRESHOLDS["nifty50"])


def _check_atr(row: pd.Series, data: pd.DataFrame, instrument_key: str) -> dict[str, Any]:
    cfg = _thresholds(instrument_key)
    spot = float(row.get("close") or 0)
    atr = float(row.get("atr") or 0)
    min_pts = float(cfg["min_atr_pts"])
    min_pct = float(cfg["min_atr_pct"])
    median_mult = float(cfg["atr_median_mult"])
    atr_pct = (atr / spot * 100) if spot > 0 else 0.0
    median_atr = float(data["atr"].tail(20).median()) if "atr" in data.columns and len(data) >= 5 else atr
    ok = atr >= min_pts and atr_pct >= min_pct and atr >= median_atr * median_mult
    return {
        "ok": ok,
        "atr": round(atr, 2),
        "atr_pct": round(atr_pct, 3),
        "median_atr": round(median_atr, 2),
        "threshold_pts": min_pts,
        "detail": f"ATR {atr:.1f} ({atr_pct:.2f}%) vs min {min_pts:.0f} pts",
    }


def _check_volume(row: pd.Series, instrument_key: str) -> dict[str, Any]:
    cfg = _thresholds(instrument_key)
    min_ratio = float(cfg["min_volume_ratio"])
    ratio = float(row.get("volume_ratio") or 0)
    ok = ratio >= min_ratio
    return {
        "ok": ok,
        "volume_ratio": round(ratio, 2),
        "threshold": min_ratio,
        "detail": f"volume {ratio:.2f}x vs {min_ratio:.2f}x avg(20)",
    }


def _check_adx(row: pd.Series, instrument_key: str) -> dict[str, Any]:
    cfg = _thresholds(instrument_key)
    min_adx = float(cfg["min_adx"])
    adx_val = float(row.get("adx14") or 0)
    ok = adx_val >= min_adx
    return {
        "ok": ok,
        "adx": round(adx_val, 1),
        "threshold": min_adx,
        "detail": f"ADX {adx_val:.1f} vs min {min_adx:.0f}",
    }


def _parse_event_time(raw: Any) -> datetime | None:
    if raw is None:
        return None
    try:
        dt = pd.to_datetime(raw, errors="coerce")
        if pd.isna(dt):
            return None
        if dt.tzinfo is None:
            return dt.to_pydatetime().replace(tzinfo=IST)
        return dt.astimezone(IST)
    except (TypeError, ValueError):
        return None


def _check_news(macro_inputs: dict[str, Any] | None, ts: Any = None) -> dict[str, Any]:
    macro = macro_inputs or {}
    block_min = int(macro.get("news_block_minutes") or _thresholds("nifty50")["news_block_minutes"])
    now = _to_ist(ts)
    horizon = now + timedelta(minutes=block_min)
    events = macro.get("economic_events") or macro.get("events") or macro.get("news_events") or []
    blocking: list[str] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        impact = str(ev.get("impact") or ev.get("severity") or "high").lower()
        if impact in ("low", "1"):
            continue
        at = _parse_event_time(ev.get("at") or ev.get("time") or ev.get("datetime"))
        if at is None:
            continue
        if now <= at <= horizon:
            blocking.append(str(ev.get("title") or ev.get("name") or "scheduled event"))
    if macro.get("news_block") or macro.get("block_trading"):
        blocking.append(str(macro.get("news_block_reason") or "macro news block active"))
    ok = len(blocking) == 0
    return {
        "ok": ok,
        "blocking_events": blocking[:5],
        "block_minutes": block_min,
        "detail": "no major events in window" if ok else f"events: {', '.join(blocking[:3])}",
    }


def _check_spread(
    row: pd.Series,
    tick: dict[str, Any] | None,
    instrument_key: str,
) -> dict[str, Any]:
    cfg = _thresholds(instrument_key)
    max_bps = float(cfg["max_spread_bps"])
    max_range_pct = float(cfg["max_range_spread_pct"])
    spot = float(row.get("close") or 0)
    bid = ask = None
    if tick:
        bid = float(tick.get("bid") or 0) or None
        ask = float(tick.get("ask") or 0) or None
    if bid and ask and ask >= bid and spot > 0:
        mid = (bid + ask) / 2
        spread_bps = (ask - bid) / mid * 10_000 if mid > 0 else 999.0
        ok = spread_bps <= max_bps
        return {
            "ok": ok,
            "spread_bps": round(spread_bps, 2),
            "threshold_bps": max_bps,
            "detail": f"spread {spread_bps:.1f} bps vs max {max_bps:.0f}",
        }
    # Without live bid/ask, 1m bar range is a poor spread proxy and blocks most bars in backtest.
    return {"ok": True, "detail": "spread check skipped — no live quote"}


# Mean-reversion / RSI-cross / SMC setups are valid in a sideways 15m tape.
# SMC uses its own bias_mode (e.g. block_opposite); hard MTF alignment over-blocks ranging days.
_SIDEWAYS_OK_STRATEGIES = frozenset({"vwap_bounce", "ema_crossover_rsi", "smc_orb_fvg", "smc_fvg_ob_bos"})


def _check_mtf(
    mtf_context: dict[str, Any] | None,
    signal_type: str | None,
    strategy_id: str | None = None,
) -> dict[str, Any]:
    mtf = mtf_context or {}
    trend_15m = str(mtf.get("trend_15m") or "sideways").lower()
    alignment = str(mtf.get("alignment_15m") or "neutral").lower()
    st = str(signal_type or "").upper()
    sid = str(strategy_id or "").lower()
    allow_sideways = sid in _SIDEWAYS_OK_STRATEGIES

    if st in ("CALL", "PUT"):
        if trend_15m == "up" and st == "CALL":
            ok = alignment != "counter"
        elif trend_15m == "down" and st == "PUT":
            ok = alignment != "counter"
        elif trend_15m == "sideways":
            ok = allow_sideways
        else:
            ok = False
        detail = f"15m {trend_15m} / {alignment} vs {st}"
    else:
        ok = trend_15m in ("up", "down") and alignment != "counter"
        if not ok and allow_sideways and trend_15m == "sideways":
            ok = True
        detail = f"15m trend {trend_15m} ({alignment})"

    return {
        "ok": ok,
        "trend_15m": trend_15m,
        "alignment_15m": alignment,
        "signal_type": st or None,
        "detail": detail,
    }


def evaluate_adaptive_session(
    df: pd.DataFrame,
    *,
    instrument_key: str = "nifty50",
    tick: dict[str, Any] | None = None,
    mtf_context: dict[str, Any] | None = None,
    macro_inputs: dict[str, Any] | None = None,
    signal_type: str | None = None,
    ts: Any = None,
    skip_mtf: bool = False,
) -> dict[str, Any]:
    """
    Evaluate whether market conditions allow scalping entries.
    Returns structured checklist used by desk, strategies, and backtest.
    """
    from trading_shared.strategies.scalping_desk.engine import enrich_candles

    now = _to_ist(ts)
    hours = {
        "ok": in_market_hours(now),
        "detail": "inside NSE session" if in_market_hours(now) else "outside NSE session (9:20–15:15 IST)",
    }
    if not hours["ok"]:
        return {
            "session_ok": False,
            "mode": "adaptive",
            "checks": {"market_hours": hours},
            "failed": ["market_hours"],
            "summary": hours["detail"],
            "evaluated_at": now.isoformat(),
        }

    if df is None or len(df) < 21:
        return {
            "session_ok": False,
            "mode": "adaptive",
            "checks": {"market_hours": hours, "data": {"ok": False, "detail": "need ≥21 bars"}},
            "failed": ["data"],
            "summary": "insufficient candle history for adaptive session",
            "evaluated_at": now.isoformat(),
        }

    data = df if "adx14" in df.columns and "volume_ratio" in df.columns else enrich_candles(df)
    row = data.iloc[-1]
    if ts is None:
        ts = row.get("timestamp")

    if mtf_context is None and len(data) >= 30:
        from trading_shared.strategies.scalping_desk.mtf_context_builder import build_mtf_analysis

        spot = float(row.get("close") or 0)
        mtf_context = build_mtf_analysis(data, spot=spot)

    checks: dict[str, Any] = {
        "market_hours": hours,
        "atr": _check_atr(row, data, instrument_key),
        "volume": _check_volume(row, instrument_key),
        "adx": _check_adx(row, instrument_key),
        "news_clear": _check_news(macro_inputs, ts),
        "spread": _check_spread(row, tick, instrument_key),
    }
    if not skip_mtf:
        checks["mtf_align"] = _check_mtf(mtf_context, signal_type)

    required = ["atr", "volume", "adx", "news_clear", "spread"] + ([] if skip_mtf else ["mtf_align"])
    failed = [name for name in required if not checks[name].get("ok")]
    session_ok = len(failed) == 0
    summary = "adaptive session open" if session_ok else f"blocked: {', '.join(failed)}"

    return {
        "session_ok": session_ok,
        "mode": "adaptive",
        "checks": checks,
        "failed": failed,
        "summary": summary,
        "evaluated_at": now.isoformat(),
        "instrument_key": instrument_key,
    }


def in_adaptive_session(
    df: pd.DataFrame,
    *,
    instrument_key: str = "nifty50",
    tick: dict[str, Any] | None = None,
    mtf_context: dict[str, Any] | None = None,
    macro_inputs: dict[str, Any] | None = None,
    signal_type: str | None = None,
    ts: Any = None,
    skip_mtf: bool = False,
) -> bool:
    return evaluate_adaptive_session(
        df,
        instrument_key=instrument_key,
        tick=tick,
        mtf_context=mtf_context,
        macro_inputs=macro_inputs,
        signal_type=signal_type,
        ts=ts,
        skip_mtf=skip_mtf,
    )["session_ok"]


def mtf_aligns_with_signal(
    mtf_context: dict[str, Any] | None,
    signal_type: str | None,
    strategy_id: str | None = None,
) -> bool:
    """Per-signal 15m trend alignment check."""
    return _check_mtf(mtf_context, signal_type, strategy_id=strategy_id)["ok"]


def _row_session_checks(
    row: pd.Series,
    data: pd.DataFrame,
    instrument_key: str,
    *,
    trend_15m: str = "sideways",
    ts: Any = None,
) -> dict[str, bool]:
    """Fast per-bar checks using pre-enriched OHLCV (no MTF rebuild)."""
    if not in_market_hours(ts or row.get("timestamp")):
        return {"market_hours": False}
    checks = {
        "market_hours": True,
        "atr": _check_atr(row, data, instrument_key)["ok"],
        "volume": _check_volume(row, instrument_key)["ok"],
        "adx": _check_adx(row, instrument_key)["ok"],
        "mtf_align": trend_15m in ("up", "down"),
    }
    return checks


def precompute_backtest_session_mask(
    data: pd.DataFrame,
    instrument_key: str,
) -> list[bool]:
    """
    Vectorized adaptive session mask for backtest replay.
    Avoids rebuilding MTF context on every bar (major speedup).
    """
    if data is None or data.empty:
        return []
    frame = data.reset_index(drop=True)
    trend_15m = _approximate_15m_trends(frame)
    rolling_atr_median = (
        frame["atr"].rolling(20, min_periods=5).median() if "atr" in frame.columns else pd.Series(0.0, index=frame.index)
    )
    cfg = _thresholds(instrument_key)
    min_pts = float(cfg["min_atr_pts"])
    min_pct = float(cfg["min_atr_pct"])
    median_mult = float(cfg["atr_median_mult"])
    min_vol = float(cfg["min_volume_ratio"])
    min_adx = float(cfg["min_adx"])

    mask: list[bool] = []
    for i in range(len(frame)):
        row = frame.iloc[i]
        ts = row.get("timestamp")
        if not in_market_hours(ts):
            mask.append(False)
            continue
        spot = float(row.get("close") or 0)
        atr = float(row.get("atr") or 0)
        atr_pct = (atr / spot * 100) if spot > 0 else 0.0
        atr_median = float(rolling_atr_median.iloc[i] or atr)
        atr_ok = atr >= min_pts and atr_pct >= min_pct and atr >= atr_median * median_mult
        vol_ok = float(row.get("volume_ratio") or 0) >= min_vol
        adx_ok = float(row.get("adx14") or 0) >= min_adx
        mtf_ok = trend_15m[i] in ("up", "down")
        mask.append(atr_ok and vol_ok and adx_ok and mtf_ok)
    return mask


def _approximate_15m_trends(data: pd.DataFrame) -> list[str]:
    """Map 15m EMA trend to each 1m bar without full MTF analysis."""
    n = len(data)
    if "timestamp" not in data.columns or n < 20:
        return ["sideways"] * n
    ts = pd.to_datetime(data["timestamp"], errors="coerce")
    close = pd.to_numeric(data["close"], errors="coerce").fillna(0.0)
    ema9 = close.ewm(span=9, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()
    work = pd.DataFrame({"ts": ts, "ema9": ema9, "ema21": ema21, "close": close})
    work = work[work["ts"].notna()]
    if len(work) < 20:
        return ["sideways"] * n
    work = work.set_index("ts")
    resampled = work.resample("15min").last().dropna(how="any")
    bucket_trend: dict[Any, str] = {}
    for bucket, row in resampled.iterrows():
        e9, e21 = float(row["ema9"]), float(row["ema21"])
        if e9 > e21 * 1.0002:
            bucket_trend[bucket] = "up"
        elif e9 < e21 * 0.9998:
            bucket_trend[bucket] = "down"
        else:
            bucket_trend[bucket] = "sideways"
    trends: list[str] = []
    for raw_ts in ts:
        if pd.isna(raw_ts):
            trends.append("sideways")
            continue
        bucket = pd.Timestamp(raw_ts).floor("15min")
        trends.append(bucket_trend.get(bucket, "sideways"))
    return trends
