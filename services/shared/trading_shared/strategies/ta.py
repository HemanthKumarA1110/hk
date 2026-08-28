"""Technical analysis helpers for strategy engines."""

from __future__ import annotations

import pandas as pd


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length, min_periods=1).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=length, min_periods=length).mean()
    avg_loss = loss.rolling(window=length, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-9)
    return (100 - (100 / (1 + rs))).fillna(50)


def vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    tp = (high + low + close) / 3
    cum_tpv = (tp * volume).cumsum()
    cum_vol = volume.cumsum().replace(0, 1)
    return cum_tpv / cum_vol


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    fast_ema = ema(close, fast)
    slow_ema = ema(close, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "hist": macd_line - signal_line})


def supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.Series:
    hl2 = (df["high"] + df["low"]) / 2
    atr = (df["high"] - df["low"]).rolling(period).mean()
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    st = pd.Series(index=df.index, dtype=float)
    direction = pd.Series(1, index=df.index)
    for i in range(1, len(df)):
        if df["close"].iloc[i] > upper.iloc[i - 1]:
            direction.iloc[i] = 1
        elif df["close"].iloc[i] < lower.iloc[i - 1]:
            direction.iloc[i] = -1
        else:
            direction.iloc[i] = direction.iloc[i - 1]
        st.iloc[i] = lower.iloc[i] if direction.iloc[i] == 1 else upper.iloc[i]
    return st * direction


def bollinger_bands(close: pd.Series, length: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    mid = sma(close, length)
    std = close.rolling(length).std().fillna(0)
    return pd.DataFrame({"mid": mid, "upper": mid + std_dev * std, "lower": mid - std_dev * std})


def opening_range(df: pd.DataFrame, bars: int = 15) -> tuple[float, float]:
    segment = df.head(min(bars, len(df)))
    return float(segment["high"].max()), float(segment["low"].min())


def adx_components(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.DataFrame:
    """Wilder ADX + DI components for trend-strength gating."""
    high = pd.to_numeric(high, errors="coerce").fillna(0.0)
    low = pd.to_numeric(low, errors="coerce").fillna(0.0)
    close = pd.to_numeric(close, errors="coerce").fillna(0.0)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    alpha = 1 / period
    atr_w = tr.ewm(alpha=alpha, adjust=False).mean().replace(0, pd.NA)
    plus_di = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_w
    minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_w
    di_sum = (plus_di + minus_di).replace(0, pd.NA)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    dx = pd.to_numeric(dx, errors="coerce").fillna(0.0)
    adx_s = dx.ewm(alpha=alpha, adjust=False).mean().fillna(0.0)
    return pd.DataFrame(
        {
            "adx": adx_s,
            "plus_di": pd.to_numeric(plus_di, errors="coerce").fillna(0.0),
            "minus_di": pd.to_numeric(minus_di, errors="coerce").fillna(0.0),
        }
    )


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder ADX(period) for trend-strength gating."""
    return adx_components(high, low, close, period=period)["adx"]


def add_common_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema9"] = ema(out["close"], 9)
    out["ema20"] = ema(out["close"], 20)
    out["ema50"] = ema(out["close"], 50)
    out["rsi14"] = rsi(out["close"], 14)
    out["vwap"] = vwap(out["high"], out["low"], out["close"], out["volume"])
    out["vol_avg20"] = out["volume"].rolling(20, min_periods=1).mean()
    out["vol_spike"] = out["volume"] > out["vol_avg20"] * 1.5
    return out
