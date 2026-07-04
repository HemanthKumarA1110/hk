"""Daily-bar helpers, costs, and indicator enrichment for swing desk."""

from __future__ import annotations

import pandas as pd

from trading_shared.strategies.ta import ema, rsi, sma

BROKERAGE_PCT = 0.0003
SLIPPAGE_PCT = 0.0002
STT_SELL_PCT = 0.001  # 0.1% on sell side (delivery equity)

WARMUP_BARS = 210


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def enrich_swing_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if "timestamp" not in out.columns:
        out["timestamp"] = pd.RangeIndex(len(out))
    out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, format="mixed", errors="coerce")
    out["ema20"] = ema(out["close"], 20)
    out["ema50"] = ema(out["close"], 50)
    out["ema200"] = ema(out["close"], 200)
    out["rsi14"] = rsi(out["close"], 14)
    out["vol_avg20"] = out["volume"].rolling(20, min_periods=1).mean()
    out["atr14"] = atr(out, 14)
    out["high_close_20"] = out["close"].shift(1).rolling(20, min_periods=20).max()
    return out


def bar_date(ts) -> object:
    if hasattr(ts, "date"):
        return ts.date()
    return pd.to_datetime(ts, utc=True, format="mixed", errors="coerce").date()


def swing_entry_cost(entry_price: float, qty: int) -> float:
    leg_rate = BROKERAGE_PCT + SLIPPAGE_PCT
    return entry_price * qty * leg_rate


def swing_exit_cost(exit_price: float, qty: int) -> float:
    exit_notional = exit_price * qty
    leg_rate = BROKERAGE_PCT + SLIPPAGE_PCT
    return exit_notional * leg_rate + exit_notional * STT_SELL_PCT


def swing_transaction_cost(entry_price: float, exit_price: float, qty: int) -> float:
    return swing_entry_cost(entry_price, qty) + swing_exit_cost(exit_price, qty)


def swing_low(df: pd.DataFrame, idx: int, lookback: int = 5) -> float:
    start = max(0, idx - lookback + 1)
    return float(df["low"].iloc[start : idx + 1].min())


def swing_high(df: pd.DataFrame, idx: int, lookback: int = 5) -> float:
    start = max(0, idx - lookback + 1)
    return float(df["high"].iloc[start : idx + 1].max())


def position_qty(equity: float, entry: float, stoploss: float, risk_pct: float = 1.0) -> int:
    if entry <= 0 or entry <= stoploss:
        return 0
    risk_amount = equity * (risk_pct / 100)
    stop_distance = entry - stoploss
    if stop_distance <= 0:
        return 0
    qty = int(risk_amount // stop_distance)
    return max(qty, 1)


def position_notional(qty: int, price: float) -> float:
    return qty * price
