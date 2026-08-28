"""IST session helpers and intraday indicator enrichment."""

from __future__ import annotations

from datetime import time

import pandas as pd

from trading_shared.strategies.ta import adx_components, ema, rsi

IST = "Asia/Kolkata"
MARKET_OPEN = time(9, 15)
OPENING_RANGE_END = time(9, 45)
FORCE_EXIT_TIME = time(15, 15)
MARKET_CLOSE = time(15, 30)

# Equity cash MIS approximate round-trip cost model (India).
BROKERAGE_PCT = 0.0003  # 0.03% per leg
SLIPPAGE_PCT = 0.00015  # 0.015% per leg (slightly conservative)
STT_SELL_PCT = 0.00025  # 0.025% on sell turnover (intraday)
EXCHANGE_PCT = 0.0000297  # ~0.00297% per leg
SEBI_PCT = 0.000001  # 0.0001% per leg
STAMP_BUY_PCT = 0.00003  # ~0.003% on buy
GST_ON_FEES = 0.18


def parse_timestamp(ts) -> pd.Timestamp:
    """Parse mixed ISO / naive candle timestamps safely (naive = IST market time)."""
    if ts is None or (isinstance(ts, float) and pd.isna(ts)):
        return pd.NaT
    if isinstance(ts, pd.Timestamp):
        parsed = ts
    else:
        parsed = pd.to_datetime(ts, format="mixed", errors="coerce")
    if pd.isna(parsed):
        return pd.NaT
    if parsed.tzinfo is None:
        return parsed.tz_localize(IST, ambiguous="NaT", nonexistent="shift_forward")
    return parsed.tz_convert(IST)


def normalize_timestamp_series(series: pd.Series) -> pd.Series:
    """Normalize a timestamp column to timezone-aware IST (naive treated as IST)."""
    # Element-wise to support mixed naive + offset strings without utc=True shifting IST bars.
    return series.map(parse_timestamp)


def bar_time(ts) -> time:
    parsed = parse_timestamp(ts)
    if pd.isna(parsed):
        return time(0, 0)
    return parsed.time()


def trading_date(ts):
    parsed = parse_timestamp(ts)
    if pd.isna(parsed):
        return pd.NaT
    return parsed.date()


def is_regular_session(ts) -> bool:
    t = bar_time(ts)
    return MARKET_OPEN <= t <= MARKET_CLOSE


def is_after_opening_range(ts) -> bool:
    return bar_time(ts) >= OPENING_RANGE_END


def is_force_exit_bar(ts, force_exit_time: time | None = None) -> bool:
    cutoff = force_exit_time or FORCE_EXIT_TIME
    return bar_time(ts) >= cutoff


def is_opening_range_bar(ts, or_end: time | None = None) -> bool:
    t = bar_time(ts)
    end = or_end or OPENING_RANGE_END
    return MARKET_OPEN <= t < end


def is_entry_window(ts, start: time, end: time) -> bool:
    t = bar_time(ts)
    return start <= t <= end


def interval_minutes(df: pd.DataFrame) -> int:
    if len(df) < 2 or "timestamp" not in df.columns:
        return 5
    a = parse_timestamp(df["timestamp"].iloc[0])
    b = parse_timestamp(df["timestamp"].iloc[1])
    if pd.isna(a) or pd.isna(b):
        return 5
    delta = b - a
    return max(int(delta.total_seconds() // 60), 1)


def daily_vwap(day_df: pd.DataFrame) -> pd.Series:
    tp = (day_df["high"] + day_df["low"] + day_df["close"]) / 3
    cum_tpv = (tp * day_df["volume"]).cumsum()
    cum_vol = day_df["volume"].cumsum().replace(0, 1)
    return cum_tpv / cum_vol


def opening_range_for_day(
    day_df: pd.DataFrame,
    or_end: time | None = None,
) -> tuple[float | None, float | None]:
    segment = day_df[day_df["timestamp"].apply(lambda ts: is_opening_range_bar(ts, or_end=or_end))]
    if segment.empty:
        return None, None
    return float(segment["high"].max()), float(segment["low"].min())


def swing_low(df: pd.DataFrame, idx: int, lookback: int = 5) -> float:
    start = max(0, idx - lookback + 1)
    return float(df["low"].iloc[start : idx + 1].min())


def swing_high(df: pd.DataFrame, idx: int, lookback: int = 5) -> float:
    start = max(0, idx - lookback + 1)
    return float(df["high"].iloc[start : idx + 1].max())


def sanitize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Repair corrupt broker/DB candles where open/low are zeroed."""
    out = df.copy()
    if "close" not in out.columns:
        return out
    close = out["close"].astype(float)
    prev_close = close.shift(1)

    if "open" in out.columns:
        open_px = out["open"].astype(float)
        bad_open = (open_px <= 0) & (close > 0)
        repaired_open = prev_close.where(prev_close > 0, close)
        out.loc[bad_open, "open"] = repaired_open.loc[bad_open]

    if "low" in out.columns:
        low = out["low"].astype(float)
        bad_low = (low <= 0) & (close > 0)
        open_px = out["open"].astype(float) if "open" in out.columns else close
        repaired_low = pd.concat([open_px, close], axis=1).min(axis=1)
        out.loc[bad_low, "low"] = repaired_low.loc[bad_low]

    if "high" in out.columns:
        high = out["high"].astype(float)
        bad_high = (high <= 0) & (close > 0)
        open_px = out["open"].astype(float) if "open" in out.columns else close
        repaired_high = pd.concat([open_px, close], axis=1).max(axis=1)
        out.loc[bad_high, "high"] = repaired_high.loc[bad_high]

    # Ensure high/low brackets open/close after repair.
    if {"open", "high", "low", "close"}.issubset(out.columns):
        o = out["open"].astype(float)
        h = out["high"].astype(float)
        l = out["low"].astype(float)
        c = out["close"].astype(float)
        out["high"] = pd.concat([h, o, c], axis=1).max(axis=1)
        out["low"] = pd.concat([l, o, c], axis=1).min(axis=1)
    return out


def _attach_htf_trend(
    out: pd.DataFrame,
    *,
    htf_minutes: int = 15,
    htf_ema_fast: int = 50,
    htf_ema_slow: int = 200,
) -> pd.DataFrame:
    """Resample to higher timeframe and forward-fill confirmed HTF EMAs onto 5m bars."""
    if out.empty or "timestamp" not in out.columns:
        return out
    frame = out.set_index("timestamp").sort_index()
    rule = f"{max(1, int(htf_minutes))}min"
    htf = (
        frame.resample(rule, label="right", closed="right")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["close"])
    )
    if htf.empty:
        out["htf_close"] = pd.NA
        out["htf_ema_fast"] = pd.NA
        out["htf_ema_slow"] = pd.NA
        out["htf_ema_fast_prev"] = pd.NA
        return out
    htf["htf_ema_fast"] = ema(htf["close"], int(htf_ema_fast))
    htf["htf_ema_slow"] = ema(htf["close"], int(htf_ema_slow))
    htf["htf_ema_fast_prev"] = htf["htf_ema_fast"].shift(1)
    htf["htf_close"] = htf["close"]
    # Shift by 1 HTF bar so 5m bars only see completed HTF candles (no look-ahead).
    htf_safe = htf[["htf_close", "htf_ema_fast", "htf_ema_slow", "htf_ema_fast_prev"]].shift(1)
    aligned = htf_safe.reindex(frame.index, method="ffill")
    for col in aligned.columns:
        out[col] = aligned[col].to_numpy()
    return out


def enrich_intraday_frame(
    df: pd.DataFrame,
    *,
    or_end: time | None = None,
    ema_periods: list[int] | None = None,
    vol_lookback: int = 20,
    ema_trend_period: int | None = None,
    adx_period: int = 14,
    atr_period: int = 14,
    rsi_period: int = 14,
    htf_minutes: int | None = None,
    htf_ema_fast: int = 50,
    htf_ema_slow: int = 200,
) -> pd.DataFrame:
    """Add session-aware VWAP, EMAs, RSI, and volume averages."""
    if df.empty:
        return df

    out = sanitize_ohlcv(df)
    if "timestamp" not in out.columns:
        out["timestamp"] = pd.RangeIndex(len(out))

    out["timestamp"] = normalize_timestamp_series(out["timestamp"])
    out["trade_date"] = out["timestamp"].apply(trading_date)

    vwap_vals: list[float] = []
    for _, day_df in out.groupby("trade_date", sort=False):
        vwap_vals.extend(daily_vwap(day_df).tolist())
    out["vwap"] = vwap_vals

    periods = list(ema_periods or [9, 21])
    trend_p = int(ema_trend_period or 21)
    if trend_p not in periods:
        periods.append(trend_p)
    for period in periods:
        out[f"ema{period}"] = ema(out["close"], int(period))
    out["ema_trend"] = out[f"ema{trend_p}"]
    rsi_len = max(2, int(rsi_period))
    out["rsi14"] = rsi(out["close"], 14)
    if rsi_len != 14:
        out[f"rsi{rsi_len}"] = rsi(out["close"], rsi_len)
    lookback = max(1, int(vol_lookback))
    out["vol_avg20"] = out["volume"].rolling(20, min_periods=1).mean()
    out[f"vol_avg{lookback}"] = out["volume"].rolling(lookback, min_periods=1).mean()
    out["vol_rising"] = out["volume"] > out["volume"].shift(1).fillna(out["volume"])
    vol_avg_col = f"vol_avg{lookback}"
    if vol_avg_col in out.columns:
        out["volume_ratio"] = out["volume"] / out[vol_avg_col].replace(0, 1)
    else:
        out["volume_ratio"] = out["volume"] / out["vol_avg20"].replace(0, 1)
    prev_close = out["close"].shift(1)
    tr = pd.concat(
        [
            (out["high"] - out["low"]).abs(),
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_len = max(1, int(atr_period))
    out["atr"] = tr.rolling(atr_len, min_periods=1).mean()
    adx_len = max(1, int(adx_period))
    di = adx_components(out["high"], out["low"], out["close"], period=adx_len)
    out["adx14"] = di["adx"]
    out["plus_di"] = di["plus_di"]
    out["minus_di"] = di["minus_di"]

    or_high: list[float | None] = []
    or_low: list[float | None] = []
    for _, day_df in out.groupby("trade_date", sort=False):
        hi, lo = opening_range_for_day(day_df, or_end=or_end)
        or_high.extend([hi] * len(day_df))
        or_low.extend([lo] * len(day_df))
    out["or_high"] = or_high
    out["or_low"] = or_low

    if htf_minutes:
        out = _attach_htf_trend(
            out,
            htf_minutes=int(htf_minutes),
            htf_ema_fast=int(htf_ema_fast),
            htf_ema_slow=int(htf_ema_slow),
        )
    return out


def enrich_for_strategy(df: pd.DataFrame, strategy_code: str | None = None) -> pd.DataFrame:
    """Enrich candles with strategy-aware ORB / indicator settings when needed."""
    if strategy_code == "INTRA-ORB":
        from trading_shared.strategies.intraday_desk.intra_orb_tuning import (
            merge_intra_orb_params,
            minutes_to_time,
        )

        p = merge_intra_orb_params(None)
        return enrich_intraday_frame(
            df,
            or_end=minutes_to_time(int(p["or_end_min"])),
            ema_periods=[9, 21, int(p["ema_period"])],
            vol_lookback=int(p["vol_lookback"]),
            ema_trend_period=int(p["ema_period"]),
        )
    if strategy_code == "INTRA-VWAP-ORB":
        from trading_shared.strategies.intraday_desk.intra_vwap_orb_tuning import (
            merge_intra_vwap_orb_params,
            minutes_to_time,
        )

        p = merge_intra_vwap_orb_params(None)
        return enrich_intraday_frame(
            df,
            or_end=minutes_to_time(int(p["or_end_min"])),
            ema_periods=[int(p["ema_fast"]), int(p["ema_slow"])],
            vol_lookback=int(p["vol_lookback"]),
            ema_trend_period=int(p["ema_slow"]),
            atr_period=int(p["atr_period"]),
        )
    return enrich_intraday_frame(df)


def transaction_cost(entry_price: float, exit_price: float, qty: int) -> float:
    """Round-trip equity MIS costs: brokerage, slippage, STT, exchange, SEBI, stamp, GST."""
    entry_notional = entry_price * qty
    exit_notional = exit_price * qty
    brokerage = (entry_notional + exit_notional) * BROKERAGE_PCT
    slippage = (entry_notional + exit_notional) * SLIPPAGE_PCT
    exchange = (entry_notional + exit_notional) * EXCHANGE_PCT
    sebi = (entry_notional + exit_notional) * SEBI_PCT
    stt = exit_notional * STT_SELL_PCT
    stamp = entry_notional * STAMP_BUY_PCT
    gst = (brokerage + exchange + sebi) * GST_ON_FEES
    return brokerage + slippage + exchange + sebi + stt + stamp + gst


COST_MODEL_LABEL = (
    "equity MIS: 0.03% brokerage + 0.015% slippage/leg + STT 0.025% sell "
    "+ exchange/SEBI + stamp ~0.003% buy + 18% GST on fees"
)


def position_qty(equity: float, entry: float, stoploss: float, risk_pct: float = 1.0) -> int:
    if entry <= 0 or entry == stoploss:
        return 0
    risk_amount = equity * (risk_pct / 100)
    stop_distance = abs(entry - stoploss)
    if stop_distance <= 0:
        return 0
    qty = int(risk_amount // stop_distance)
    return max(qty, 1)
