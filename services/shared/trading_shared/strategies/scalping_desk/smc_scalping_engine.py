"""
Smart Money Concepts (SMC) scalping engine.

Three modular strategies:
  1. FVG + Order Block + Break of Structure
  2. Liquidity Sweep + M/W reversal
  3. Opening Range Breakout + FVG retest

Multi-timeframe: 15m bias, 5m structure, 1m execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd

from trading_shared.strategies.scalping_desk.engine import (
    ScalpSignal,
    compute_scalp_risk,
    enrich_candles,
    max_hold_bars,
    pick_strike,
    premium_risk_from_index,
    risk_profile,
)

DEFAULT_SMC_PARAMS: dict[str, float | int] = {
    "stop_atr_mult": 1.0,
    "target_atr_mult": 1.6,
    "trailing_atr_mult": 0.75,
    "entry_buffer_pct": 0.12,
    "volume_min": 0.95,
    "swing_lookback": 5,
    "ob_impulse_atr": 1.0,
    "fvg_min_gap_pct": 0.008,
    "liquidity_equal_tol_pct": 0.08,
    "orb_minutes": 15,
    "bos_lookback_1m": 8,
    "bos_lookback_5m": 5,
    "max_hold_bars": 12,
}

SMC_STRATEGY_IDS = ("smc_fvg_ob_bos", "smc_liquidity_sweep", "smc_orb_fvg")


@dataclass
class SMCSetup:
    strategy_id: str
    signal_type: str  # CALL | PUT
    bias: str
    entry_zone: tuple[float, float]
    conditions: list[str] = field(default_factory=list)
    stop_pts: float = 0
    target_pts: float = 0


@dataclass
class MTFContext:
    bias_15m: str  # bullish | bearish | neutral
    structure_5m: str
    df_1m: pd.DataFrame
    df_5m: pd.DataFrame
    df_15m: pd.DataFrame
    session_orb: dict[str, float] | None = None


@dataclass
class PrecomputedMTF:
    """Full-series MTF frames for fast backtest slicing."""

    data_1m: pd.DataFrame
    data_5m: pd.DataFrame
    data_15m: pd.DataFrame
    session_orbs: dict[str, dict[str, float]] = field(default_factory=dict)


def resample_ohlcv(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Resample 1m OHLCV to higher timeframe."""
    if df.empty:
        return df
    frame = df.copy()
    if "timestamp" in frame.columns:
        frame["ts"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        frame = frame.set_index("ts")
    elif not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.RangeIndex(len(frame))
        return frame

    ohlcv = frame.resample(f"{minutes}min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()
    ohlcv = ohlcv.reset_index()
    ohlcv.rename(columns={"ts": "timestamp"}, inplace=True)
    return ohlcv


def build_mtf_context(df_1m: pd.DataFrame) -> MTFContext:
    """Build 15m/5m/1m frames from 1m history."""
    pre = prepare_mtf_frames(df_1m)
    return mtf_context_at(pre, len(pre.data_1m) - 1)


def prepare_mtf_frames(df_1m: pd.DataFrame) -> PrecomputedMTF:
    """Enrich and resample once for backtest replay."""
    data_1m = enrich_candles(df_1m) if "ema9" not in df_1m.columns else df_1m.copy()
    raw = df_1m if "timestamp" in df_1m.columns else data_1m
    df_5m = resample_ohlcv(raw, 5)
    df_15m = resample_ohlcv(raw, 15)
    if len(df_5m) >= 10:
        df_5m = enrich_candles(df_5m)
    if len(df_15m) >= 5:
        df_15m = enrich_candles(df_15m)

    session_orbs: dict[str, dict[str, float]] = {}
    if "timestamp" in data_1m.columns:
        orb_frame = data_1m.copy()
        orb_frame["ts"] = pd.to_datetime(orb_frame["timestamp"], errors="coerce")
        orb_frame = orb_frame.dropna(subset=["ts"])
        for day, group in orb_frame.groupby(orb_frame["ts"].dt.date):
            segment = group.head(int(DEFAULT_SMC_PARAMS.get("orb_minutes", 15)))
            if len(segment) < 5:
                continue
            hi = float(segment["high"].max())
            lo = float(segment["low"].min())
            session_orbs[str(day)] = {"high": hi, "low": lo, "mid": (hi + lo) / 2}

    return PrecomputedMTF(data_1m=data_1m, data_5m=df_5m, data_15m=df_15m, session_orbs=session_orbs)


def mtf_context_at(pre: PrecomputedMTF, end_idx: int, lookback: int = 90) -> MTFContext:
    """Slice precomputed MTF frames at bar index (fast backtest path)."""
    start = max(0, end_idx + 1 - lookback)
    s1 = pre.data_1m.iloc[start : end_idx + 1]
    ts_end = pd.to_datetime(s1.iloc[-1].get("timestamp"), errors="coerce")

    s5 = pre.data_5m
    s15 = pre.data_15m
    if not s5.empty and ts_end is not pd.NaT:
        s5_ts = pd.to_datetime(s5["timestamp"], errors="coerce")
        s5 = s5.loc[s5_ts <= ts_end].tail(max(24, lookback // 5 + 4))
    if not s15.empty and ts_end is not pd.NaT:
        s15_ts = pd.to_datetime(s15["timestamp"], errors="coerce")
        s15 = s15.loc[s15_ts <= ts_end].tail(max(16, lookback // 15 + 4))

    bias = _htf_bias(s15) if len(s15) >= 5 else "neutral"
    structure = _structure_bias(s5) if len(s5) >= 6 else "neutral"
    session_orb = None
    if ts_end is not pd.NaT:
        session_orb = pre.session_orbs.get(str(ts_end.date()))
    return MTFContext(
        bias_15m=bias,
        structure_5m=structure,
        df_1m=s1,
        df_5m=s5,
        df_15m=s15,
        session_orb=session_orb,
    )


def _htf_bias(df_15m: pd.DataFrame) -> str:
    if len(df_15m) < 5:
        return "neutral"
    tail = df_15m.tail(8)
    highs = _swing_highs(tail, 2)
    lows = _swing_lows(tail, 2)
    if len(highs) >= 2 and highs[-1] > highs[-2]:
        return "bullish"
    if len(lows) >= 2 and lows[-1] < lows[-2]:
        return "bearish"
    row = tail.iloc[-1]
    if float(row.get("ema9", 0)) > float(row.get("ema21", 0)) and float(row.get("close", 0)) > float(row.get("vwap", 0)):
        return "bullish"
    if float(row.get("ema9", 0)) < float(row.get("ema21", 0)) and float(row.get("close", 0)) < float(row.get("vwap", 0)):
        return "bearish"
    return "neutral"


def _structure_bias(df_5m: pd.DataFrame) -> str:
    if len(df_5m) < 6:
        return "neutral"
    return _htf_bias(df_5m)


def _swing_highs(df: pd.DataFrame, lookback: int) -> list[float]:
    highs: list[float] = []
    for i in range(lookback, len(df) - lookback):
        window = df.iloc[i - lookback : i + lookback + 1]
        h = float(df.iloc[i]["high"])
        if h >= float(window["high"].max()):
            highs.append(h)
    return highs


def _swing_lows(df: pd.DataFrame, lookback: int) -> list[float]:
    lows: list[float] = []
    for i in range(lookback, len(df) - lookback):
        window = df.iloc[i - lookback : i + lookback + 1]
        l = float(df.iloc[i]["low"])
        if l <= float(window["low"].min()):
            lows.append(l)
    return lows


def structure_break(
    df: pd.DataFrame,
    direction: str,
    *,
    lookback: int = 8,
    price: float | None = None,
    completed_only: bool = False,
) -> bool:
    """Close/price breaks the prior N-bar range (practical BOS for replay)."""
    if df.empty or len(df) < lookback + 1:
        return False
    work = df.iloc[:-1] if completed_only and len(df) > 1 else df
    if len(work) < lookback:
        return False
    px = float(price if price is not None else work.iloc[-1]["close"])
    prior = work.iloc[-lookback:]
    if direction == "bullish":
        return px > float(prior["high"].max())
    if direction == "bearish":
        return px < float(prior["low"].min())
    return False


def detect_bos(
    df: pd.DataFrame,
    direction: str,
    lookback: int = 5,
    *,
    price: float | None = None,
) -> bool:
    """Break of structure — swing break or prior-range break."""
    if len(df) < lookback + 2:
        return False
    px = float(price if price is not None else df.iloc[-1]["close"])
    work = df.iloc[:-1] if len(df) > 1 else df
    tail = work.tail(max(lookback + 10, 12))
    highs = _swing_highs(tail, 2)
    lows = _swing_lows(tail, 2)
    if direction == "bullish":
        if highs and px > highs[-1]:
            return True
        return structure_break(work, "bullish", lookback=lookback, price=px)
    if direction == "bearish":
        if lows and px < lows[-1]:
            return True
        return structure_break(work, "bearish", lookback=lookback, price=px)
    return False


def has_bos(
    mtf: MTFContext,
    direction: str,
    params: dict[str, Any],
    *,
    spot: float | None = None,
) -> bool:
    """5m completed-bar BOS with 1m execution fallback."""
    px = spot if spot is not None else float(mtf.df_1m.iloc[-1]["close"])
    lb5 = int(params.get("bos_lookback_5m", 5))
    lb1 = int(params.get("bos_lookback_1m", 8))
    if detect_bos(mtf.df_5m, direction, lb5, price=px):
        return True
    return detect_bos(mtf.df_1m, direction, lb1, price=px)


def detect_fvg(df: pd.DataFrame, min_gap_pct: float = 0.02) -> list[dict[str, Any]]:
    """Fair Value Gaps: candle1 high < candle3 low (bull), candle1 low > candle3 high (bear)."""
    gaps: list[dict[str, Any]] = []
    for i in range(2, len(df)):
        c1, c3 = df.iloc[i - 2], df.iloc[i]
        mid = float(df.iloc[i - 1]["close"])
        if float(c1["high"]) < float(c3["low"]):
            gap = float(c3["low"]) - float(c1["high"])
            if gap / max(mid, 1) * 100 >= min_gap_pct:
                gaps.append({"type": "bullish", "top": float(c3["low"]), "bottom": float(c1["high"]), "index": i})
        if float(c1["low"]) > float(c3["high"]):
            gap = float(c1["low"]) - float(c3["high"])
            if gap / max(mid, 1) * 100 >= min_gap_pct:
                gaps.append({"type": "bearish", "top": float(c1["low"]), "bottom": float(c3["high"]), "index": i})
    return gaps[-5:]


def detect_order_block(df: pd.DataFrame, direction: str, impulse_atr: float = 1.2) -> dict[str, Any] | None:
    """Last opposite candle before strong impulse move."""
    if len(df) < 6:
        return None
    tail = df.tail(12)
    atr = float(tail["atr"].iloc[-1] or tail["close"].iloc[-1] * 0.002)
    for i in range(len(tail) - 3, 0, -1):
        prev = tail.iloc[i - 1]
        cur = tail.iloc[i]
        nxt = tail.iloc[i + 1]
        move = abs(float(nxt["close"]) - float(cur["close"]))
        if move < atr * impulse_atr:
            continue
        if direction == "bullish" and float(prev["close"]) < float(prev["open"]):
            return {"top": float(prev["high"]), "bottom": float(prev["low"]), "index": i - 1}
        if direction == "bearish" and float(prev["close"]) > float(prev["open"]):
            return {"top": float(prev["high"]), "bottom": float(prev["low"]), "index": i - 1}
    return None


def _in_zone(price: float, zone: dict[str, Any] | tuple, buffer_pct: float) -> bool:
    if isinstance(zone, tuple):
        lo, hi = zone
    else:
        lo, hi = zone["bottom"], zone["top"]
    mid = (hi + lo) / 2
    span = max(hi - lo, mid * 0.0005)
    pad = max(span * buffer_pct, mid * 0.0012)
    return lo - pad <= price <= hi + pad


def _rejection(row: pd.Series, direction: str) -> bool:
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    body = abs(c - o)
    rng = max(h - l, 0.01)
    if direction == "bullish":
        lower_wick = min(o, c) - l
        if c > o and body / rng >= 0.55:
            return True
        return c >= o and lower_wick / rng >= 0.28 and body / rng <= 0.72
    upper_wick = h - max(o, c)
    if c < o and body / rng >= 0.55:
        return True
    return c <= o and upper_wick / rng >= 0.28 and body / rng <= 0.72


def detect_equal_levels(df: pd.DataFrame, tol_pct: float = 0.06) -> dict[str, list[float]]:
    highs = _swing_highs(df.tail(40), 2)
    lows = _swing_lows(df.tail(40), 2)
    eq_highs: list[float] = []
    eq_lows: list[float] = []
    for i, h1 in enumerate(highs):
        for h2 in highs[i + 1 :]:
            if abs(h1 - h2) / max(h1, 1) * 100 <= tol_pct:
                eq_highs.append((h1 + h2) / 2)
    for i, l1 in enumerate(lows):
        for l2 in lows[i + 1 :]:
            if abs(l1 - l2) / max(l1, 1) * 100 <= tol_pct:
                eq_lows.append((l1 + l2) / 2)
    return {"equal_highs": eq_highs[-3:], "equal_lows": eq_lows[-3:]}


def detect_liquidity_sweep(df: pd.DataFrame, level: float, direction: str) -> bool:
    """Wick through level then close back inside."""
    row = df.iloc[-1]
    h, l, c = float(row["high"]), float(row["low"]), float(row["close"])
    if direction == "bearish" and h > level and c < level:
        return True
    if direction == "bullish" and l < level and c > level:
        return True
    return False


def detect_w_pattern(df: pd.DataFrame) -> bool:
    lows = _swing_lows(df.tail(20), 2)
    if len(lows) < 2:
        return False
    return abs(lows[-1] - lows[-2]) / max(lows[-1], 1) * 100 <= 0.15 and float(df.iloc[-1]["close"]) > lows[-1]


def detect_m_pattern(df: pd.DataFrame) -> bool:
    highs = _swing_highs(df.tail(20), 2)
    if len(highs) < 2:
        return False
    return abs(highs[-1] - highs[-2]) / max(highs[-1], 1) * 100 <= 0.15 and float(df.iloc[-1]["close"]) < highs[-1]


def opening_range(df: pd.DataFrame, orb_minutes: int = 15, session_orb: dict[str, float] | None = None) -> dict[str, float] | None:
    """First N minutes high/low for the current session day."""
    if session_orb:
        return session_orb
    if len(df) < orb_minutes or "timestamp" not in df.columns:
        return None
    frame = df.copy()
    frame["ts"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame = frame.dropna(subset=["ts"])
    if frame.empty:
        return None
    session_day = frame["ts"].iloc[-1].date()
    segment = frame.loc[frame["ts"].dt.date == session_day].head(orb_minutes)
    if len(segment) < max(5, orb_minutes // 2):
        return None
    hi = float(segment["high"].max())
    lo = float(segment["low"].min())
    return {"high": hi, "low": lo, "mid": float((hi + lo) / 2)}


# ── Strategy evaluators ──────────────────────────────────────────────────────


def _resolve_bias(mtf: MTFContext) -> str:
    if mtf.bias_15m != "neutral":
        return mtf.bias_15m
    return mtf.structure_5m if mtf.structure_5m != "neutral" else "neutral"


def evaluate_fvg_ob_bos_setup(mtf: MTFContext, params: dict[str, Any]) -> SMCSetup | None:
    bias = _resolve_bias(mtf)
    if bias == "neutral":
        return None
    direction = "bullish" if bias == "bullish" else "bearish"

    df5, df1 = mtf.df_5m, mtf.df_1m
    if len(df5) < 8 or len(df1) < 5:
        return None

    row = df1.iloc[-1]
    spot = float(row["close"])
    vol = float(row.get("volume_ratio", 1))
    if vol < float(params.get("volume_min", 0.95)):
        return None

    structure_ok = (
        has_bos(mtf, direction, params, spot=spot)
        or mtf.structure_5m == direction
        or (mtf.structure_5m == "neutral" and mtf.bias_15m == direction)
    )
    if not structure_ok:
        return None

    ob = detect_order_block(df5, direction, float(params.get("ob_impulse_atr", 1.0)))
    fvgs = detect_fvg(df1, float(params.get("fvg_min_gap_pct", 0.008)))
    if not ob and not fvgs:
        return None

    buffer = float(params.get("entry_buffer_pct", 0.12))
    in_ob = ob and _in_zone(spot, ob, buffer)
    fvg_hit = any(
        f["type"] == ("bullish" if direction == "bullish" else "bearish") and _in_zone(spot, f, buffer)
        for f in fvgs
    )
    near_vwap = abs(spot - float(row.get("vwap", spot))) / max(spot, 1) * 100 <= 0.2
    trend_ok = (
        (direction == "bullish" and float(row.get("ema9", spot)) >= float(row.get("ema21", spot)))
        or (direction == "bearish" and float(row.get("ema9", spot)) <= float(row.get("ema21", spot)))
    )
    if not (in_ob or fvg_hit or (ob and near_vwap) or (trend_ok and (ob or fvgs))):
        return None

    if not _rejection(row, direction):
        return None

    atr = float(row.get("atr") or spot * 0.002)
    stop = atr * float(params.get("stop_atr_mult", 1.0))
    target = atr * float(params.get("target_atr_mult", 1.6))
    zone = (ob["bottom"], ob["top"]) if ob else (fvgs[-1]["bottom"], fvgs[-1]["top"])

    return SMCSetup(
        strategy_id="smc_fvg_ob_bos",
        signal_type="CALL" if direction == "bullish" else "PUT",
        bias=bias,
        entry_zone=zone,
        conditions=["htf_bos", "order_block_or_fvg", "rejection", f"vol_{vol:.1f}"],
        stop_pts=round(stop, 2),
        target_pts=round(target, 2),
    )


def evaluate_liquidity_sweep_setup(mtf: MTFContext, params: dict[str, Any]) -> SMCSetup | None:
    df5, df1 = mtf.df_5m, mtf.df_1m
    if len(df5) < 10 or len(df1) < 5:
        return None

    eq = detect_equal_levels(df5, float(params.get("liquidity_equal_tol_pct", 0.08)))
    row = df1.iloc[-1]
    spot = float(row["close"])
    vol = float(row.get("volume_ratio", 1))
    if vol < float(params.get("volume_min", 0.95)):
        return None

    bias = _resolve_bias(mtf)

    # Bearish: sweep equal highs + rejection (M pattern optional)
    for level in eq.get("equal_highs", []):
        if bias == "bullish":
            continue
        if detect_liquidity_sweep(df1, level, "bearish") and _rejection(row, "bearish"):
            if has_bos(mtf, "bearish", params, spot=spot) or detect_m_pattern(df5):
                atr = float(row.get("atr") or spot * 0.002)
                return SMCSetup(
                    strategy_id="smc_liquidity_sweep",
                    signal_type="PUT",
                    bias="bearish",
                    entry_zone=(level * 0.999, level * 1.001),
                    conditions=["liquidity_sweep_high", "bos_or_m_pattern"],
                    stop_pts=round(atr * float(params["stop_atr_mult"]), 2),
                    target_pts=round(atr * float(params["target_atr_mult"]), 2),
                )

    for level in eq.get("equal_lows", []):
        if bias == "bearish":
            continue
        if detect_liquidity_sweep(df1, level, "bullish") and _rejection(row, "bullish"):
            if has_bos(mtf, "bullish", params, spot=spot) or detect_w_pattern(df5):
                atr = float(row.get("atr") or spot * 0.002)
                return SMCSetup(
                    strategy_id="smc_liquidity_sweep",
                    signal_type="CALL",
                    bias="bullish",
                    entry_zone=(level * 0.999, level * 1.001),
                    conditions=["liquidity_sweep_low", "bos_or_w_pattern"],
                    stop_pts=round(atr * float(params["stop_atr_mult"]), 2),
                    target_pts=round(atr * float(params["target_atr_mult"]), 2),
                )
    return None


def evaluate_orb_fvg_setup(mtf: MTFContext, params: dict[str, Any]) -> SMCSetup | None:
    df1 = mtf.df_1m
    if len(df1) < 20:
        return None

    orb = opening_range(df1, int(params.get("orb_minutes", 15)), mtf.session_orb)
    if not orb:
        return None

    row = df1.iloc[-1]
    spot = float(row["close"])
    vol = float(row.get("volume_ratio", 1))
    if vol < float(params.get("volume_min", 0.95)):
        return None

    ts = pd.to_datetime(row.get("timestamp"), errors="coerce")
    if ts is not pd.NaT and (ts.hour < 9 or (ts.hour == 9 and ts.minute < 30)):
        return None

    fvgs = detect_fvg(df1.tail(30), float(params.get("fvg_min_gap_pct", 0.008)))
    buffer = float(params.get("entry_buffer_pct", 0.12))
    bias = _resolve_bias(mtf)
    orb_pad = orb["mid"] * 0.0008

    # Bullish ORB breakout + FVG retest (or momentum continuation)
    if bias != "bearish" and spot > orb["high"] - orb_pad:
        bull_fvgs = [f for f in fvgs if f["type"] == "bullish"]
        fvg_hit = bull_fvgs and _in_zone(spot, bull_fvgs[-1], buffer)
        momentum = spot > orb["mid"] and float(row.get("ema9", spot)) >= float(row.get("ema21", spot))
        if (spot > orb["high"] or momentum) and (fvg_hit or momentum) and _rejection(row, "bullish"):
            atr = float(row.get("atr") or spot * 0.002)
            zone = (bull_fvgs[-1]["bottom"], bull_fvgs[-1]["top"]) if bull_fvgs else (orb["high"], orb["high"] * 1.001)
            return SMCSetup(
                strategy_id="smc_orb_fvg",
                signal_type="CALL",
                bias=bias if bias != "neutral" else "bullish",
                entry_zone=zone,
                conditions=["orb_breakout_up", "fvg_or_momentum"],
                stop_pts=round(atr * float(params["stop_atr_mult"]), 2),
                target_pts=round(atr * float(params["target_atr_mult"]), 2),
            )

    if bias != "bullish" and spot < orb["low"] + orb_pad:
        bear_fvgs = [f for f in fvgs if f["type"] == "bearish"]
        fvg_hit = bear_fvgs and _in_zone(spot, bear_fvgs[-1], buffer)
        momentum = spot < orb["mid"] and float(row.get("ema9", spot)) <= float(row.get("ema21", spot))
        if (spot < orb["low"] or momentum) and (fvg_hit or momentum) and _rejection(row, "bearish"):
            atr = float(row.get("atr") or spot * 0.002)
            zone = (bear_fvgs[-1]["bottom"], bear_fvgs[-1]["top"]) if bear_fvgs else (orb["low"] * 0.999, orb["low"])
            return SMCSetup(
                strategy_id="smc_orb_fvg",
                signal_type="PUT",
                bias=bias if bias != "neutral" else "bearish",
                entry_zone=zone,
                conditions=["orb_breakout_down", "fvg_or_momentum"],
                stop_pts=round(atr * float(params["stop_atr_mult"]), 2),
                target_pts=round(atr * float(params["target_atr_mult"]), 2),
            )
    return None


SMC_EVALUATORS: dict[str, Callable[[MTFContext, dict[str, Any]], SMCSetup | None]] = {
    "smc_fvg_ob_bos": evaluate_fvg_ob_bos_setup,
    "smc_liquidity_sweep": evaluate_liquidity_sweep_setup,
    "smc_orb_fvg": evaluate_orb_fvg_setup,
}

SMC_REGISTRY: dict[str, dict[str, Any]] = {
    "smc_fvg_ob_bos": {
        "id": "smc_fvg_ob_bos",
        "label": "SMC FVG + OB + BOS",
        "description": "15m bias · 5m BOS · OB/FVG retest · 1m rejection",
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN"],
    },
    "smc_liquidity_sweep": {
        "id": "smc_liquidity_sweep",
        "label": "SMC Liquidity Sweep",
        "description": "Equal highs/lows sweep · M/W pattern · structure shift",
        "best_regimes": ["RANGING", "HIGH_VOLATILITY"],
    },
    "smc_orb_fvg": {
        "id": "smc_orb_fvg",
        "label": "SMC ORB + FVG",
        "description": "Opening range breakout · FVG pullback continuation",
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"],
    },
}


def setup_to_signal(
    setup: SMCSetup,
    mtf: MTFContext,
    timeframe: str,
    option_chain: dict[str, Any],
    instrument_key: str,
    params: dict[str, Any],
) -> ScalpSignal | None:
    """Convert SMC setup to ScalpSignal for desk execution."""
    df1 = mtf.df_1m
    row = df1.iloc[-1]
    spot = float(row["close"])
    strike_info = pick_strike(option_chain, spot, setup.signal_type)
    if not strike_info:
        return None

    stop_pts = setup.stop_pts or float(row.get("atr", spot * 0.002))
    target_pts = setup.target_pts or stop_pts * 1.5
    hold = int(params.get("max_hold_bars", max_hold_bars(instrument_key)))

    option_ltp = float(strike_info.get("ltp") or strike_info.get("premium") or 1)
    sl_points, target_points = premium_risk_from_index(option_ltp, stop_pts, target_pts)

    if setup.signal_type == "CALL":
        entry = option_ltp
        stoploss = round(entry - sl_points, 2)
        target = round(entry + target_points, 2)
    else:
        entry = option_ltp
        stoploss = round(entry + sl_points, 2)
        target = round(entry - target_points, 2)

    indicators = {
        "ema9": round(float(row.get("ema9", spot)), 2),
        "ema21": round(float(row.get("ema21", spot)), 2),
        "rsi": round(float(row.get("rsi14", 50)), 2),
        "vwap": round(float(row.get("vwap", spot)), 2),
        "atr": round(float(row.get("atr", spot * 0.002)), 2),
        "spot": round(spot, 2),
        "index_stop_pts": stop_pts,
        "index_target_pts": target_pts,
        "max_hold_bars": hold,
        "strategy_id": setup.strategy_id,
        "smc_bias": setup.bias,
        "entry_zone": setup.entry_zone,
    }

    return ScalpSignal(
        signal_type=setup.signal_type,
        strike=float(strike_info["strike"]),
        option_symbol=str(strike_info["symbol"]),
        option_token=str(strike_info.get("token") or ""),
        entry=round(entry, 2),
        target=target,
        stoploss=stoploss,
        timeframe=timeframe,
        indicators=indicators,
        conditions_met=setup.conditions + [setup.strategy_id],
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def evaluate_smc_strategy(
    strategy_id: str,
    df: pd.DataFrame,
    timeframe: str,
    option_chain: dict[str, Any],
    lot_size: int,
    *,
    instrument_key: str = "nifty50",
    params: dict[str, Any] | None = None,
    skip_session: bool = False,
) -> ScalpSignal | None:
    """Evaluate one SMC strategy on latest candles."""
    if len(df) < 60:
        return None
    merged_params = {**DEFAULT_SMC_PARAMS, **(params or {})}
    mtf = build_mtf_context(df)
    evaluator = SMC_EVALUATORS.get(strategy_id)
    if not evaluator:
        return None
    setup = evaluator(mtf, merged_params)
    if not setup:
        return None
    return setup_to_signal(setup, mtf, timeframe, option_chain, instrument_key, merged_params)


def evaluate_smc_best(
    df: pd.DataFrame,
    timeframe: str,
    option_chain: dict[str, Any],
    lot_size: int,
    *,
    instrument_key: str = "nifty50",
    params: dict[str, Any] | None = None,
    fixed_strategy_id: str | None = None,
) -> tuple[ScalpSignal | None, dict[str, Any]]:
    """Try SMC strategies in priority order; return signal + metadata."""
    order = [fixed_strategy_id] if fixed_strategy_id else list(SMC_STRATEGY_IDS)
    order = [s for s in order if s in SMC_EVALUATORS]
    mtf = build_mtf_context(df)
    meta = {
        "strategy_family": "smc",
        "regime": mtf.bias_15m,
        "market_context": {
            "regime": mtf.bias_15m.upper() if mtf.bias_15m != "neutral" else "RANGING",
            "direction": mtf.bias_15m,
            "structure_5m": mtf.structure_5m,
            "bias_15m": mtf.bias_15m,
        },
        "rankings": [],
    }
    merged = {**DEFAULT_SMC_PARAMS, **(params or {})}
    for sid in order:
        setup = SMC_EVALUATORS[sid](mtf, merged)
        if setup:
            sig = setup_to_signal(setup, mtf, timeframe, option_chain, instrument_key, merged)
            if sig:
                meta["selected_strategy"] = sid
                meta["selected_label"] = SMC_REGISTRY[sid]["label"]
                meta["selection_reason"] = "; ".join(setup.conditions)
                return sig, meta
    return None, meta


def list_smc_strategies() -> list[dict[str, Any]]:
    return [
        {"id": v["id"], "label": v["label"], "description": v["description"], "best_regimes": v["best_regimes"]}
        for v in SMC_REGISTRY.values()
    ]
