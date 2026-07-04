"""Opening Range Breakout — first-bar breakout with midpoint stop and trend filter."""

from __future__ import annotations

from datetime import time

import pandas as pd

from trading_shared.strategies.intraday_desk.strategies.base import IntradaySignal, IntradayStrategy
from trading_shared.strategies.intraday_desk.session import is_after_opening_range, is_entry_window, is_force_exit_bar

ORB_ENTRY_END = time(11, 30)
MIN_OR_WIDTH_PCT = 0.25
MAX_OR_WIDTH_PCT = 1.6
MIN_RR = 2.0
VOL_MULT = 1.5
BREAKOUT_BUFFER_PCT = 0.08


class OpeningRangeBreakout(IntradayStrategy):
    id = "orb"
    code = "INTRA-ORB"

    def try_entry(self, df: pd.DataFrame, idx: int, traded_today: bool) -> IntradaySignal | None:
        if traded_today or idx < 1:
            return None

        row = df.iloc[idx]
        prev = df.iloc[idx - 1]
        ts = row["timestamp"]
        if not is_after_opening_range(ts) or is_force_exit_bar(ts):
            return None
        if not is_entry_window(ts, time(9, 45), ORB_ENTRY_END):
            return None

        or_high = row.get("or_high")
        or_low = row.get("or_low")
        if or_high is None or or_low is None or pd.isna(or_high) or pd.isna(or_low):
            return None

        or_high = float(or_high)
        or_low = float(or_low)
        if or_high <= or_low:
            return None

        close = float(row["close"])
        open_px = float(row["open"])
        prev_close = float(prev["close"])
        width = or_high - or_low
        width_pct = width / close * 100 if close else 0
        if width_pct < MIN_OR_WIDTH_PCT or width_pct > MAX_OR_WIDTH_PCT:
            return None

        # First breakout bar only — previous close inside the range
        if not (or_low <= prev_close <= or_high):
            return None

        vol = float(row["volume"])
        vol_avg = float(row.get("vol_avg20") or vol)
        if vol <= vol_avg * VOL_MULT:
            return None

        ema9 = float(row.get("ema9") or close)
        ema21 = float(row.get("ema21") or close)
        buffer = close * (BREAKOUT_BUFFER_PCT / 100)

        if close > or_high + buffer and close > open_px and close > ema21:
            stop = round((or_high + or_low) / 2, 2)
            risk = close - stop
            if risk <= 0 or risk > close * 0.008:
                return None
            target = round(close + MIN_RR * risk, 2)
            return IntradaySignal(
                side="BUY",
                entry=close,
                stoploss=stop,
                target=target,
                strategy_id=self.id,
                strategy_code=self.code,
            )

        # Short ORB disabled — long-only improves Nifty cash win rate in backtests
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
