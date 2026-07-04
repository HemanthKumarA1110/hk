"""20-day breakout with volume confirmation and ATR chandelier trail (long-only)."""

from __future__ import annotations

import pandas as pd

from trading_shared.strategies.swing_desk.strategies.base import SwingSignal, SwingStrategy

VOL_MULT = 1.25
BREAKOUT_BUFFER_PCT = 0.1
CHANDELIER_MULT = 2.5


class BreakoutAtrStrategy(SwingStrategy):
    id = "breakout_atr"
    code = "SWING-BO-ATR"
    max_hold_days = 45

    def try_entry(self, df: pd.DataFrame, idx: int, in_position: bool) -> SwingSignal | None:
        if in_position or idx < 210:
            return None
        row = df.iloc[idx]
        close = float(row["close"])
        ema200 = float(row.get("ema200") or close)
        if close <= ema200:
            return None

        prior_high = row.get("high_close_20")
        if prior_high is None or pd.isna(prior_high):
            return None
        prior_high = float(prior_high)
        buffer = close * (BREAKOUT_BUFFER_PCT / 100)

        vol = float(row["volume"])
        vol_avg = float(row.get("vol_avg20") or vol)
        atr_val = float(row.get("atr14") or 0)
        if close <= prior_high + buffer or vol <= vol_avg * VOL_MULT or atr_val <= 0:
            return None

        ema20 = float(row.get("ema20") or close)
        ema50 = float(row.get("ema50") or close)
        if ema20 < ema50:
            return None

        return SwingSignal(
            entry=close,
            stoploss=round(close - 2 * atr_val, 2),
            strategy_id=self.id,
            strategy_code=self.code,
            max_hold_days=self.max_hold_days,
            use_chandelier=True,
            chandelier_atr_mult=CHANDELIER_MULT,
        )

    def try_exit(self, position: dict, df: pd.DataFrame, idx: int) -> tuple[float, str] | None:
        row = df.iloc[idx]
        self.update_position(position, row)
        close = float(row["close"])
        entry = float(position["entry_price"])
        risk = entry - float(position["stoploss"])
        target = entry + 2.5 * risk if risk > 0 else entry * 1.1

        if self._hold_days_exceeded(position, idx):
            return close, "max_hold"
        if close >= target:
            return close, "target"
        if self._stop_hit(position, row):
            return float(position["stoploss"]), "chandelier_stop"
        return None
