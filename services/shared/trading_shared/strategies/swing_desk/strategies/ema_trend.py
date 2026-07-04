"""20/50 EMA crossover trend-following (long-only, filtered)."""

from __future__ import annotations

import pandas as pd

from trading_shared.strategies.swing_desk.session import swing_low
from trading_shared.strategies.swing_desk.strategies.base import SwingSignal, SwingStrategy

MIN_EMA_SEP_PCT = 0.15
VOL_MULT = 1.05
TRAIL_PCT = 5.5
MAX_STOP_PCT = 5.5
MAX_EXTENSION_PCT = 12.0


class EmaTrendStrategy(SwingStrategy):
    id = "ema_trend"
    code = "SWING-EMA"
    max_hold_days = 45

    def try_entry(self, df: pd.DataFrame, idx: int, in_position: bool) -> SwingSignal | None:
        if in_position or idx < 55:
            return None
        row = df.iloc[idx]
        prev = df.iloc[idx - 1]
        close = float(row["close"])
        ema20 = float(row["ema20"])
        ema50 = float(row["ema50"])
        ema200 = float(row.get("ema200") or close)
        prev_ema20 = float(prev["ema20"])
        prev_ema50 = float(prev["ema50"])

        if close <= ema200 or ema50 < ema200 * 0.995:
            return None
        if ema20 <= prev_ema20:
            return None

        extension = (close - ema20) / ema20 * 100 if ema20 else 0
        if extension > MAX_EXTENSION_PCT:
            return None

        sep_pct = (ema20 - ema50) / close * 100 if close else 0
        if sep_pct < MIN_EMA_SEP_PCT:
            return None

        vol = float(row["volume"])
        vol_avg = float(row.get("vol_avg20") or vol)
        if vol <= vol_avg * VOL_MULT:
            return None

        if prev_ema20 <= prev_ema50 and ema20 > ema50 and close > ema20 and close > ema50:
            swing_stop = swing_low(df, idx, 10)
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
                trailing_pct=TRAIL_PCT,
            )
        return None

    def try_exit(self, position: dict, df: pd.DataFrame, idx: int) -> tuple[float, str] | None:
        if idx < 1:
            return None
        row = df.iloc[idx]
        prev = df.iloc[idx - 1]
        self.update_position(position, row)

        entry = float(position["entry_price"])
        close = float(row["close"])
        risk = entry - float(position["stoploss"])
        target = entry + 2.5 * risk if risk > 0 else entry * 1.08

        if self._hold_days_exceeded(position, idx):
            return close, "max_hold"
        if close >= target:
            return close, "target"
        if float(prev["ema20"]) >= float(prev["ema50"]) and float(row["ema20"]) < float(row["ema50"]):
            return close, "ema_cross"
        if self._stop_hit(position, row):
            return float(position["stoploss"]), "trailing_stop"
        return None
