"""VWAP trend — daily VWAP cross with EMA alignment and trailing stop."""

from __future__ import annotations

from datetime import time

import pandas as pd

from trading_shared.strategies.intraday_desk.strategies.base import IntradaySignal, IntradayStrategy
from trading_shared.strategies.intraday_desk.session import is_entry_window, is_force_exit_bar, is_regular_session


class VwapTrendStrategy(IntradayStrategy):
    id = "vwap_trend"
    code = "INTRA-VWAP"

    def try_entry(self, df: pd.DataFrame, idx: int, traded_today: bool) -> IntradaySignal | None:
        if traded_today or idx < 2:
            return None

        row = df.iloc[idx]
        prev = df.iloc[idx - 1]
        ts = row["timestamp"]
        if not is_regular_session(ts) or is_force_exit_bar(ts):
            return None
        if not is_entry_window(ts, time(9, 50), time(14, 30)):
            return None

        close = float(row["close"])
        prev_close = float(prev["close"])
        vwap = float(row["vwap"])
        prev_vwap = float(prev["vwap"])
        ema9 = float(row["ema9"])

        if not bool(row.get("vol_rising")):
            return None

        if prev_close <= prev_vwap and close > vwap and ema9 > vwap:
            stop = round(close * 0.99, 2)
            return IntradaySignal(
                side="BUY",
                entry=close,
                stoploss=stop,
                target=close,
                trailing_pct=1.0,
                strategy_id=self.id,
                strategy_code=self.code,
            )

        if prev_close >= prev_vwap and close < vwap and ema9 < vwap:
            stop = round(close * 1.01, 2)
            return IntradaySignal(
                side="SELL",
                entry=close,
                stoploss=stop,
                target=close,
                trailing_pct=1.0,
                strategy_id=self.id,
                strategy_code=self.code,
            )
        return None

    def try_exit(self, position: dict, df: pd.DataFrame, idx: int) -> tuple[float, str] | None:
        row = df.iloc[idx]
        prev = df.iloc[idx - 1] if idx > 0 else row
        self.update_trailing(position, row)

        side = position["side"]
        close = float(row["close"])
        vwap = float(row["vwap"])
        prev_close = float(prev["close"])
        prev_vwap = float(prev["vwap"])

        if side == "BUY":
            if row["low"] <= position["stoploss"]:
                return position["stoploss"], "stoploss"
            if prev_close >= prev_vwap and close < vwap:
                return close, "vwap_cross"
        else:
            if row["high"] >= position["stoploss"]:
                return position["stoploss"], "stoploss"
            if prev_close <= prev_vwap and close > vwap:
                return close, "vwap_cross"
        return None
