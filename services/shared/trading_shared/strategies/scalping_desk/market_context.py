"""Live market context from streaming ticks, candles, and option chain."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from trading_shared.ai.types import MarketRegime

IST = ZoneInfo("Asia/Kolkata")


def detect_regime_from_tick(tick: dict[str, Any] | None) -> MarketRegime:
    if not tick:
        return MarketRegime.RANGING
    ltp = float(tick.get("ltp") or 0)
    open_px = float(tick.get("open") or ltp)
    high = float(tick.get("high") or ltp)
    low = float(tick.get("low") or ltp)
    prev_close = float(tick.get("close") or open_px)
    if open_px <= 0:
        return MarketRegime.RANGING
    day_range_pct = ((high - low) / open_px) * 100
    change_pct = ((ltp - prev_close) / prev_close) * 100 if prev_close else 0
    if day_range_pct > 2.0:
        return MarketRegime.HIGH_VOLATILITY
    if day_range_pct < 0.4:
        return MarketRegime.LOW_VOLATILITY
    if change_pct > 0.6:
        return MarketRegime.TRENDING_UP
    if change_pct < -0.6:
        return MarketRegime.TRENDING_DOWN
    return MarketRegime.RANGING


def detect_regime_from_candles(df: pd.DataFrame) -> MarketRegime:
    if df is None or len(df) < 10:
        return MarketRegime.RANGING
    tail = df.tail(min(60, len(df)))
    high = float(tail["high"].max())
    low = float(tail["low"].min())
    open_px = float(tail.iloc[0]["open"] or tail.iloc[0]["close"])
    close = float(tail.iloc[-1]["close"])
    if open_px <= 0:
        return MarketRegime.RANGING
    day_range_pct = ((high - low) / open_px) * 100
    change_pct = ((close - open_px) / open_px) * 100
    if day_range_pct > 1.8:
        return MarketRegime.HIGH_VOLATILITY
    if day_range_pct < 0.35:
        return MarketRegime.LOW_VOLATILITY
    if change_pct > 0.5:
        return MarketRegime.TRENDING_UP
    if change_pct < -0.5:
        return MarketRegime.TRENDING_DOWN
    return MarketRegime.RANGING


def chain_pcr(chain: dict[str, Any] | None) -> float:
    if not chain:
        return 1.0
    rows = chain.get("rows") or []
    if isinstance(rows, dict):
        rows = list(rows.values())
    ce_oi = sum(float(r.get("oi") or 0) for r in rows if str(r.get("symbol", "")).endswith("CE"))
    pe_oi = sum(float(r.get("oi") or 0) for r in rows if str(r.get("symbol", "")).endswith("PE"))
    if ce_oi <= 0:
        return 1.0
    return round(pe_oi / ce_oi, 2)


def in_trading_session(now: datetime | None = None) -> bool:
    """Battle-tested IST windows with open/close buffers."""
    from trading_shared.strategies.scalping_desk.battle_tested_scalp import in_battle_session

    return in_battle_session(now)


def build_market_context(
    df: pd.DataFrame,
    *,
    tick: dict[str, Any] | None = None,
    chain: dict[str, Any] | None = None,
    underlying: str = "NIFTY",
    pre_enriched: bool = False,
) -> dict[str, Any]:
    """Aggregate live context for AI strategy selection."""
    from trading_shared.strategies.scalping_desk.engine import enrich_candles

    regime = detect_regime_from_tick(tick) if tick else detect_regime_from_candles(df)
    if tick and regime == MarketRegime.RANGING and len(df) >= 10:
        candle_regime = detect_regime_from_candles(df)
        if candle_regime != MarketRegime.RANGING:
            regime = candle_regime

    already_enriched = pre_enriched or ("ema9" in df.columns and "volume_ratio" in df.columns)
    data = df if already_enriched or len(df) < 5 else enrich_candles(df)
    row = data.iloc[-1] if len(data) else None
    spot = float(row["close"]) if row is not None else float(tick.get("ltp") or 0) if tick else 0
    atr = float(row["atr"] or spot * 0.002) if row is not None else spot * 0.002
    vol_ratio = float(row["volume_ratio"] or 1) if row is not None else 1.0
    ema9 = float(row["ema9"] or spot) if row is not None else spot
    ema21 = float(row["ema21"] or spot) if row is not None else spot
    rsi = float(row["rsi14"] or 50) if row is not None else 50
    st_dir = float(row["supertrend_dir"] or 0) if row is not None else 0

    trend_strength = abs(ema9 - ema21) / spot * 100 if spot else 0
    direction = "up" if ema9 > ema21 and st_dir > 0 else "down" if ema9 < ema21 and st_dir < 0 else "neutral"
    pcr = chain_pcr(chain)

    ltp = float(tick.get("ltp") or spot) if tick else spot
    prev = float(tick.get("close") or tick.get("open") or ltp) if tick else spot
    spot_change_pct = round((ltp - prev) / prev * 100, 3) if prev else 0

    return {
        "regime": regime.value,
        "underlying": underlying,
        "spot": round(spot, 2),
        "atr": round(atr, 2),
        "volume_ratio": round(vol_ratio, 2),
        "trend_strength": round(trend_strength, 3),
        "direction": direction,
        "rsi": round(rsi, 2),
        "supertrend": st_dir,
        "pcr": pcr,
        "spot_change_pct": spot_change_pct,
        "session_ok": in_trading_session(),
        "stream_live": tick is not None,
    }
