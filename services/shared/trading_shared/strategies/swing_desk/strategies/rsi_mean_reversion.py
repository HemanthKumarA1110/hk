"""RSI mean-reversion with 200 EMA uptrend filter (long-only, momentum turn)."""

from __future__ import annotations

import pandas as pd

from trading_shared.strategies.swing_desk.session import swing_low
from trading_shared.strategies.swing_desk.strategies.base import SwingSignal, SwingStrategy

RSI_ENTRY = 35
RSI_EXIT = 58
MAX_STOP_PCT = 4.5


class RsiMeanReversionStrategy(SwingStrategy):
    id = "rsi_mean_reversion"
    code = "SWING-RSI"
    max_hold_days = 15

    def try_entry(self, df: pd.DataFrame, idx: int, in_position: bool) -> SwingSignal | None:
        if in_position or idx < 210:
            return None
        row = df.iloc[idx]
        prev = df.iloc[idx - 1]
        close = float(row["close"])
        rsi_val = float(row["rsi14"])
        prev_rsi = float(prev["rsi14"])
        ema200 = float(row["ema200"])

        if close <= ema200 * 1.005:
            return None
        if rsi_val >= RSI_ENTRY or rsi_val <= prev_rsi:
            return None

        vol = float(row["volume"])
        vol_avg = float(row.get("vol_avg20") or vol)
        if vol <= vol_avg:
            return None

        swing_stop = swing_low(df, idx, 5)
        pct_stop = round(close * (1 - MAX_STOP_PCT / 100), 2)
        stop = max(swing_stop, pct_stop)
        if stop >= close:
            return None

        return SwingSignal(
            entry=close,
            stoploss=round(stop, 2),
            strategy_id=self.id,
            strategy_code=self.code,
            max_hold_days=self.max_hold_days,
        )

    def try_exit(self, position: dict, df: pd.DataFrame, idx: int) -> tuple[float, str] | None:
        if idx < 1:
            return None
        row = df.iloc[idx]
        prev = df.iloc[idx - 1]
        close = float(row["close"])
        entry = float(position["entry_price"])
        risk = entry - float(position["stoploss"])
        target = entry + 2.2 * risk if risk > 0 else entry * 1.06

        if self._hold_days_exceeded(position, idx):
            return close, "max_hold"
        if close >= target:
            return close, "target"
        if float(prev["rsi14"]) <= RSI_EXIT and float(row["rsi14"]) > RSI_EXIT:
            return close, "rsi_exit"
        if self._stop_hit(position, row):
            return float(position["stoploss"]), "stoploss"
        return None
