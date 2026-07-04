"""EMA 9/21 crossover with momentum RSI and volume confirmation."""

from __future__ import annotations

from datetime import time

import pandas as pd

from trading_shared.strategies.intraday_desk.strategies.base import IntradaySignal, IntradayStrategy
from trading_shared.strategies.intraday_desk.session import is_entry_window, is_force_exit_bar, swing_high, swing_low

EMA_ENTRY_START = time(10, 0)
EMA_ENTRY_END = time(14, 30)
VOL_MULT = 1.1
MIN_EMA_SEP_PCT = 0.04
MIN_RR = 2.5


class EmaRsiStrategy(IntradayStrategy):
    id = "ema_rsi"
    code = "INTRA-EMA-RSI"

    def try_entry(self, df: pd.DataFrame, idx: int, traded_today: bool) -> IntradaySignal | None:
        if traded_today or idx < 2:
            return None

        row = df.iloc[idx]
        prev = df.iloc[idx - 1]
        ts = row["timestamp"]
        if is_force_exit_bar(ts):
            return None
        if not is_entry_window(ts, EMA_ENTRY_START, EMA_ENTRY_END):
            return None

        rsi_val = float(row["rsi14"])
        prev_rsi = float(prev["rsi14"])
        ema9 = float(row["ema9"])
        ema21 = float(row["ema21"])
        prev_ema9 = float(prev["ema9"])
        prev_ema21 = float(prev["ema21"])
        close = float(row["close"])

        vol = float(row["volume"])
        vol_avg = float(row.get("vol_avg20") or vol)
        if vol <= vol_avg * VOL_MULT:
            return None

        sep_pct = abs(ema9 - ema21) / close * 100 if close else 0
        if sep_pct < MIN_EMA_SEP_PCT:
            return None

        if prev_ema9 <= prev_ema21 and ema9 > ema21 and rsi_val >= 50 and rsi_val > prev_rsi:
            stop = swing_low(df, idx, 3)
            risk = close - stop
            if risk <= 0:
                return None
            target = round(close + MIN_RR * risk, 2)
            return IntradaySignal(
                side="BUY",
                entry=close,
                stoploss=round(stop, 2),
                target=target,
                strategy_id=self.id,
                strategy_code=self.code,
            )

        if prev_ema9 >= prev_ema21 and ema9 < ema21 and rsi_val <= 50 and rsi_val < prev_rsi:
            stop = swing_high(df, idx, 3)
            risk = stop - close
            if risk <= 0:
                return None
            target = round(close - MIN_RR * risk, 2)
            return IntradaySignal(
                side="SELL",
                entry=close,
                stoploss=round(stop, 2),
                target=target,
                strategy_id=self.id,
                strategy_code=self.code,
            )
        return None

    def try_exit(self, position: dict, df: pd.DataFrame, idx: int) -> tuple[float, str] | None:
        row = df.iloc[idx]
        side = position["side"]
        if side == "BUY":
            if row["low"] <= position["stoploss"]:
                return position["stoploss"], "stoploss"
            if row["high"] >= position["target"]:
                return position["target"], "target"
        else:
            if row["high"] >= position["stoploss"]:
                return position["stoploss"], "stoploss"
            if row["low"] <= position["target"]:
                return position["target"], "target"
        return None
