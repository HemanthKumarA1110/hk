"""
Multi-timeframe context builder for NSE derivatives scalping.

Deterministic analyst layer over 5m / 15m / 1h OHLCV. Prompt template available
for LLM extensions via `format_mtf_context_prompt`.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from trading_shared.strategies.scalping_desk.engine import enrich_candles
from trading_shared.strategies.scalping_desk.smc_scalping_engine import resample_ohlcv

MTF_CONTEXT_PROMPT = """Multi-timeframe context builder:
You are a market analyst for NSE derivatives. Given the following OHLCV data across 3 timeframes (5m, 15m, 1h), identify:
1. The dominant trend direction on the 1h chart (up/down/sideways)
2. Whether the 15m is aligned or counter-trend
3. The nearest key S/R levels on the 5m chart
4. A market bias score from -10 (strong bear) to +10 (strong bull)

5m OHLCV (recent):
{OHLCV_5M}

15m OHLCV (recent):
{OHLCV_15M}

1h OHLCV (recent):
{OHLCV_1H}

Respond ONLY in JSON format:
{{"trend_1h":"up|down|sideways","alignment_15m":"aligned|counter|neutral","sr_levels":{{"support":[],"resistance":[]}},"bias_score":0,"reasoning":"<30 words max"}}"""


def _ensure_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    frame = df.copy()
    for col in ("open", "high", "low", "close"):
        if col not in frame.columns:
            return pd.DataFrame()
    if "volume" not in frame.columns:
        frame["volume"] = 0
    return frame


def _serialize_bars(df: pd.DataFrame, n: int = 6) -> str:
    if df.empty:
        return "[]"
    tail = df.tail(n)
    rows = []
    for _, row in tail.iterrows():
        ts = row.get("timestamp", "")
        rows.append(
            {
                "t": str(ts)[:16],
                "o": round(float(row["open"]), 2),
                "h": round(float(row["high"]), 2),
                "l": round(float(row["low"]), 2),
                "c": round(float(row["close"]), 2),
                "v": round(float(row.get("volume") or 0), 0),
            }
        )
    return str(rows)


def format_mtf_context_prompt(
    *,
    df_5m: pd.DataFrame,
    df_15m: pd.DataFrame,
    df_1h: pd.DataFrame,
    bars: int = 6,
) -> str:
    return MTF_CONTEXT_PROMPT.format(
        OHLCV_5M=_serialize_bars(df_5m, bars),
        OHLCV_15M=_serialize_bars(df_15m, bars),
        OHLCV_1H=_serialize_bars(df_1h, bars),
    )


def prepare_mtf_frames(
    df: pd.DataFrame,
    *,
    enrich: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build 5m, 15m, 1h frames from intraday OHLCV (typically 1m)."""
    raw = _ensure_ohlcv(df)
    if raw.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    base = enrich_candles(raw) if enrich and "ema9" not in raw.columns else raw
    df_5m = resample_ohlcv(base, 5)
    df_15m = resample_ohlcv(base, 15)
    df_1h = resample_ohlcv(base, 60)
    if len(df_5m) >= 10:
        df_5m = enrich_candles(df_5m)
    if len(df_15m) >= 5:
        df_15m = enrich_candles(df_15m)
    if len(df_1h) >= 3:
        df_1h = enrich_candles(df_1h)
    return df_5m, df_15m, df_1h


def _swing_highs(df: pd.DataFrame, lookback: int = 2) -> list[float]:
    highs: list[float] = []
    if len(df) < lookback * 2 + 1:
        return highs
    for i in range(lookback, len(df) - lookback):
        window = df.iloc[i - lookback : i + lookback + 1]
        h = float(df.iloc[i]["high"])
        if h >= float(window["high"].max()):
            highs.append(h)
    return highs


def _swing_lows(df: pd.DataFrame, lookback: int = 2) -> list[float]:
    lows: list[float] = []
    if len(df) < lookback * 2 + 1:
        return lows
    for i in range(lookback, len(df) - lookback):
        window = df.iloc[i - lookback : i + lookback + 1]
        l = float(df.iloc[i]["low"])
        if l <= float(window["low"].min()):
            lows.append(l)
    return lows


def _trend_direction(df: pd.DataFrame, *, min_bars: int = 4) -> str:
    """Return up / down / sideways for a timeframe."""
    if df is None or len(df) < min_bars:
        return "sideways"

    tail = df.tail(max(min_bars, 8))
    open_px = float(tail.iloc[0]["open"])
    close = float(tail.iloc[-1]["close"])
    if open_px <= 0:
        return "sideways"

    change_pct = (close - open_px) / open_px * 100
    highs = _swing_highs(tail, 2)
    lows = _swing_lows(tail, 2)

    hh = len(highs) >= 2 and highs[-1] > highs[-2]
    hl = len(lows) >= 2 and lows[-1] > lows[-2]
    lh = len(highs) >= 2 and highs[-1] < highs[-2]
    ll = len(lows) >= 2 and lows[-1] < lows[-2]

    ema9 = float(tail.iloc[-1].get("ema9") or close)
    ema21 = float(tail.iloc[-1].get("ema21") or close)
    ema_sep = abs(ema9 - ema21) / close * 100 if close else 0

    bull = (hh and hl) or (change_pct > 0.25 and ema9 > ema21 and ema_sep > 0.03)
    bear = (lh and ll) or (change_pct < -0.25 and ema9 < ema21 and ema_sep > 0.03)

    if bull and not bear:
        return "up"
    if bear and not bull:
        return "down"
    if abs(change_pct) < 0.15 and ema_sep < 0.04:
        return "sideways"
    if change_pct > 0.2:
        return "up"
    if change_pct < -0.2:
        return "down"
    return "sideways"


def _alignment_15m(trend_1h: str, trend_15m: str) -> str:
    if trend_1h == "sideways" or trend_15m == "sideways":
        return "neutral"
    if trend_1h == trend_15m:
        return "aligned"
    return "counter"


def _nearest_sr_levels(
    df_5m: pd.DataFrame,
    spot: float,
    *,
    max_levels: int = 3,
    proximity_pct: float = 0.012,
) -> dict[str, list[float]]:
    if df_5m.empty or spot <= 0:
        return {"support": [], "resistance": []}

    tail = df_5m.tail(48)
    swing_hi = sorted(set(_swing_highs(tail, 2)), reverse=True)
    swing_lo = sorted(set(_swing_lows(tail, 2)))
    session_hi = float(tail["high"].max())
    session_lo = float(tail["low"].min())

    resist_candidates = sorted({*swing_hi, session_hi})
    support_candidates = sorted({*swing_lo, session_lo})

    max_dist = spot * proximity_pct
    resistance = [
        round(x, 2)
        for x in resist_candidates
        if x > spot and (x - spot) <= max_dist * 3
    ][:max_levels]
    support = [
        round(x, 2)
        for x in reversed(support_candidates)
        if x < spot and (spot - x) <= max_dist * 3
    ][:max_levels]

    if not resistance:
        resistance = [round(x, 2) for x in resist_candidates if x > spot][:max_levels]
    if not support:
        support = [round(x, 2) for x in reversed(support_candidates) if x < spot][:max_levels]

    return {"support": support, "resistance": resistance}


def _bias_score(
    trend_1h: str,
    trend_15m: str,
    alignment_15m: str,
    sr_levels: dict[str, list[float]],
    spot: float,
) -> int:
    score = 0.0
    if trend_1h == "up":
        score += 4
    elif trend_1h == "down":
        score -= 4

    if trend_15m == "up":
        score += 2
    elif trend_15m == "down":
        score -= 2

    if alignment_15m == "aligned":
        score += 2 if trend_1h == "up" else -2 if trend_1h == "down" else 0
    elif alignment_15m == "counter":
        score -= 1.5 if trend_1h == "up" else 1.5 if trend_1h == "down" else 0

    supports = sr_levels.get("support") or []
    resistances = sr_levels.get("resistance") or []
    if spot > 0 and supports:
        nearest_sup = max(supports)
        dist_sup = (spot - nearest_sup) / spot * 100
        if dist_sup < 0.08:
            score += 1.5
        elif dist_sup < 0.2:
            score += 0.5
    if spot > 0 and resistances:
        nearest_res = min(resistances)
        dist_res = (nearest_res - spot) / spot * 100
        if dist_res < 0.08:
            score -= 1.5
        elif dist_res < 0.2:
            score -= 0.5

    return int(max(-10, min(10, round(score))))


def _reasoning(
    trend_1h: str,
    alignment_15m: str,
    bias_score: int,
    sr_levels: dict[str, list[float]],
) -> str:
    sup = sr_levels.get("support") or []
    res = sr_levels.get("resistance") or []
    parts = [f"1h {trend_1h}", f"15m {alignment_15m}"]
    if sup:
        parts.append(f"sup {sup[0]}")
    if res:
        parts.append(f"res {res[0]}")
    parts.append(f"bias {bias_score:+d}")
    text = ", ".join(parts)
    return text[:120] if len(text) > 120 else text


def build_mtf_analysis(
    df: pd.DataFrame,
    *,
    spot: float | None = None,
    bars_for_prompt: int = 6,
) -> dict[str, Any]:
    """
    Analyze 5m / 15m / 1h context from intraday OHLCV.

    Returns JSON-shaped dict matching MTF_CONTEXT_PROMPT output.
    """
    df_5m, df_15m, df_1h = prepare_mtf_frames(df)
    px = spot
    if px is None or px <= 0:
        if not df.empty:
            px = float(df.iloc[-1]["close"])
        elif not df_5m.empty:
            px = float(df_5m.iloc[-1]["close"])
        else:
            px = 0.0

    trend_1h = _trend_direction(df_1h, min_bars=3)
    trend_15m = _trend_direction(df_15m, min_bars=4)
    alignment = _alignment_15m(trend_1h, trend_15m)
    sr_levels = _nearest_sr_levels(df_5m, px)
    bias = _bias_score(trend_1h, trend_15m, alignment, sr_levels, px)
    reason = _reasoning(trend_1h, alignment, bias, sr_levels)

    prompt = format_mtf_context_prompt(
        df_5m=df_5m,
        df_15m=df_15m,
        df_1h=df_1h,
        bars=bars_for_prompt,
    )

    return {
        "trend_1h": trend_1h,
        "trend_15m": trend_15m,
        "alignment_15m": alignment,
        "sr_levels": sr_levels,
        "bias_score": bias,
        "reasoning": reason,
        "spot": round(px, 2),
        "prompt": prompt,
        "frames": {
            "bars_5m": len(df_5m),
            "bars_15m": len(df_15m),
            "bars_1h": len(df_1h),
        },
    }


def merge_mtf_into_context(
    market_ctx: dict[str, Any],
    mtf: dict[str, Any],
) -> dict[str, Any]:
    """Attach MTF analysis fields to desk market_context."""
    out = dict(market_ctx)
    out["mtf"] = {
        "trend_1h": mtf.get("trend_1h"),
        "trend_15m": mtf.get("trend_15m"),
        "alignment_15m": mtf.get("alignment_15m"),
        "sr_levels": mtf.get("sr_levels"),
        "bias_score": mtf.get("bias_score"),
        "reasoning": mtf.get("reasoning"),
    }
    out["bias_score"] = mtf.get("bias_score")
    out["trend_1h"] = mtf.get("trend_1h")
    out["alignment_15m"] = mtf.get("alignment_15m")
    out["sr_levels"] = mtf.get("sr_levels")
    bias = int(mtf.get("bias_score") or 0)
    if bias >= 4:
        out["direction"] = "up"
    elif bias <= -4:
        out["direction"] = "down"
    elif not out.get("direction"):
        out["direction"] = "neutral"
    return out


def mtf_blocks_signal(mtf: dict[str, Any] | None, signal_type: str | None) -> bool:
    """Skip entries that fight a strong multi-timeframe bias."""
    if not mtf:
        return False
    st = str(signal_type or "").upper()
    if st not in ("CALL", "PUT"):
        return False
    bias = int(mtf.get("bias_score") or 0)
    alignment = str(mtf.get("alignment_15m") or "neutral")
    trend_1h = str(mtf.get("trend_1h") or "sideways")

    if alignment == "counter" and abs(bias) >= 5:
        if st == "CALL" and bias < 0:
            return True
        if st == "PUT" and bias > 0:
            return True
    if trend_1h == "up" and st == "PUT" and bias <= -6:
        return True
    if trend_1h == "down" and st == "CALL" and bias >= 6:
        return True
    return False
