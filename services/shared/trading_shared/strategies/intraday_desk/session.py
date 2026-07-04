"""IST session helpers and intraday indicator enrichment."""

from __future__ import annotations

from datetime import time

import pandas as pd

from trading_shared.strategies.ta import ema, rsi

IST = "Asia/Kolkata"
MARKET_OPEN = time(9, 15)
OPENING_RANGE_END = time(9, 45)
FORCE_EXIT_TIME = time(15, 15)
MARKET_CLOSE = time(15, 30)

BROKERAGE_PCT = 0.0003
SLIPPAGE_PCT = 0.0001


def parse_timestamp(ts) -> pd.Timestamp:
    """Parse mixed ISO / naive candle timestamps safely."""
    if ts is None or (isinstance(ts, float) and pd.isna(ts)):
        return pd.NaT
    if isinstance(ts, pd.Timestamp):
        parsed = ts
    else:
        parsed = pd.to_datetime(ts, utc=True, format="mixed", errors="coerce")
    if pd.isna(parsed):
        return pd.NaT
    if parsed.tzinfo is None:
        return parsed.tz_localize(IST, ambiguous="NaT", nonexistent="shift_forward")
    return parsed.tz_convert(IST)


def normalize_timestamp_series(series: pd.Series) -> pd.Series:
    """Normalize a timestamp column to timezone-aware IST."""
    parsed = pd.to_datetime(series, utc=True, format="mixed", errors="coerce")
    if getattr(parsed.dt, "tz", None) is None:
        return parsed.dt.tz_localize(IST, ambiguous="NaT", nonexistent="shift_forward")
    return parsed.dt.tz_convert(IST)


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


def is_force_exit_bar(ts) -> bool:
    return bar_time(ts) >= FORCE_EXIT_TIME


def is_opening_range_bar(ts) -> bool:
    t = bar_time(ts)
    return MARKET_OPEN <= t < OPENING_RANGE_END


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


def opening_range_for_day(day_df: pd.DataFrame) -> tuple[float | None, float | None]:
    segment = day_df[day_df["timestamp"].apply(is_opening_range_bar)]
    if segment.empty:
        return None, None
    return float(segment["high"].max()), float(segment["low"].min())


def swing_low(df: pd.DataFrame, idx: int, lookback: int = 5) -> float:
    start = max(0, idx - lookback + 1)
    return float(df["low"].iloc[start : idx + 1].min())


def swing_high(df: pd.DataFrame, idx: int, lookback: int = 5) -> float:
    start = max(0, idx - lookback + 1)
    return float(df["high"].iloc[start : idx + 1].max())


def enrich_intraday_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Add session-aware VWAP, EMAs, RSI, and volume averages."""
    if df.empty:
        return df

    out = df.copy()
    if "timestamp" not in out.columns:
        out["timestamp"] = pd.RangeIndex(len(out))

    out["timestamp"] = normalize_timestamp_series(out["timestamp"])
    out["trade_date"] = out["timestamp"].apply(trading_date)

    vwap_vals: list[float] = []
    for _, day_df in out.groupby("trade_date", sort=False):
        vwap_vals.extend(daily_vwap(day_df).tolist())
    out["vwap"] = vwap_vals

    out["ema9"] = ema(out["close"], 9)
    out["ema21"] = ema(out["close"], 21)
    out["rsi14"] = rsi(out["close"], 14)
    out["vol_avg20"] = out["volume"].rolling(20, min_periods=1).mean()
    out["vol_rising"] = out["volume"] > out["volume"].shift(1).fillna(out["volume"])

    or_high: list[float | None] = []
    or_low: list[float | None] = []
    for _, day_df in out.groupby("trade_date", sort=False):
        hi, lo = opening_range_for_day(day_df)
        or_high.extend([hi] * len(day_df))
        or_low.extend([lo] * len(day_df))
    out["or_high"] = or_high
    out["or_low"] = or_low
    return out


def transaction_cost(entry_price: float, exit_price: float, qty: int) -> float:
    """Round-trip brokerage + slippage (0.03% + 0.01% each leg)."""
    entry_notional = entry_price * qty
    exit_notional = exit_price * qty
    leg_rate = BROKERAGE_PCT + SLIPPAGE_PCT
    return entry_notional * leg_rate + exit_notional * leg_rate


def position_qty(equity: float, entry: float, stoploss: float, risk_pct: float = 1.0) -> int:
    if entry <= 0 or entry == stoploss:
        return 0
    risk_amount = equity * (risk_pct / 100)
    stop_distance = abs(entry - stoploss)
    if stop_distance <= 0:
        return 0
    qty = int(risk_amount // stop_distance)
    return max(qty, 1)
