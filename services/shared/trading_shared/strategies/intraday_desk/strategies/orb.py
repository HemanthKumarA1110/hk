"""Opening Range Breakout — first-bar breakout with configurable risk filters."""

from __future__ import annotations

from datetime import time
from typing import Any

import pandas as pd

from trading_shared.strategies.intraday_desk.intra_orb_tuning import (
    INTRA_ORB_DEFAULTS,
    merge_intra_orb_params,
    minutes_to_time,
)
from trading_shared.strategies.intraday_desk.strategies.base import IntradaySignal, IntradayStrategy
from trading_shared.strategies.intraday_desk.session import is_entry_window, is_force_exit_bar

# Legacy module-level aliases (tests / imports).
ORB_ENTRY_END = time(11, 30)
MIN_OR_WIDTH_PCT = float(INTRA_ORB_DEFAULTS["min_or_width_pct"])
MAX_OR_WIDTH_PCT = float(INTRA_ORB_DEFAULTS["max_or_width_pct"])
MIN_RR = float(INTRA_ORB_DEFAULTS["min_rr"])
VOL_MULT = float(INTRA_ORB_DEFAULTS["vol_mult"])
BREAKOUT_BUFFER_PCT = float(INTRA_ORB_DEFAULTS["breakout_buffer_pct"])


class OpeningRangeBreakout(IntradayStrategy):
    id = "orb"
    code = "INTRA-ORB"
    max_trades_per_day = 1

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = merge_intra_orb_params(params)

    def try_entry(self, df: pd.DataFrame, idx: int, traded_today: bool) -> IntradaySignal | None:
        if traded_today or idx < 1:
            return None

        p = self.params
        row = df.iloc[idx]
        prev = df.iloc[idx - 1]
        ts = row["timestamp"]

        force_exit = minutes_to_time(int(p["force_exit_min"]))
        if is_force_exit_bar(ts, force_exit_time=force_exit):
            return None

        or_end = minutes_to_time(int(p["or_end_min"]))
        entry_start = minutes_to_time(int(p["entry_start_min"]))
        entry_end = minutes_to_time(int(p["entry_end_min"]))
        # Entries only after OR end and inside entry window.
        from trading_shared.strategies.intraday_desk.session import bar_time

        t = bar_time(ts)
        if t < or_end:
            return None
        if not is_entry_window(ts, entry_start, entry_end):
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
        high = float(row["high"])
        low = float(row["low"])
        prev_close = float(prev["close"])
        prev_high = float(prev["high"])
        prev_low = float(prev["low"])
        width = or_high - or_low
        width_pct = width / close * 100 if close else 0
        min_w = float(p["min_or_width_pct"])
        max_w = float(p["max_or_width_pct"])
        if width_pct < min_w or width_pct > max_w:
            return None

        mode = str(p.get("first_breakout_mode") or "prev_close_inside")
        if mode == "prev_bar_inside":
            if not (or_low <= prev_low and prev_high <= or_high):
                return None
        elif mode == "prev_not_above":
            if prev_close > or_high:
                return None
        else:
            # prev_close_inside (current)
            if not (or_low <= prev_close <= or_high):
                return None

        vol = float(row["volume"])
        lookback = int(p.get("vol_lookback") or 20)
        vol_avg_col = f"vol_avg{lookback}"
        if vol_avg_col in row.index and not pd.isna(row.get(vol_avg_col)):
            vol_avg = float(row.get(vol_avg_col))
        elif "vol_avg20" in row.index and not pd.isna(row.get("vol_avg20")):
            vol_avg = float(row.get("vol_avg20") or vol)
        else:
            start = max(0, idx - lookback + 1)
            vol_avg = float(df["volume"].iloc[start : idx + 1].mean())
        if vol <= vol_avg * float(p["vol_mult"]):
            return None
        if bool(p.get("require_vol_rising")) and not bool(row.get("vol_rising", True)):
            return None

        ema_period = int(p.get("ema_period") or 21)
        ema_col = f"ema{ema_period}"
        if ema_col in row.index and not pd.isna(row.get(ema_col)):
            ema_val = float(row.get(ema_col))
        elif "ema_trend" in row.index and not pd.isna(row.get("ema_trend")):
            ema_val = float(row.get("ema_trend"))
        else:
            ema_val = float(row.get("ema21") or close)

        if close <= open_px or close <= ema_val:
            return None

        if bool(p.get("ema_slope")):
            prev_ema = None
            if ema_col in prev.index and not pd.isna(prev.get(ema_col)):
                prev_ema = float(prev.get(ema_col))
            elif "ema_trend" in prev.index and not pd.isna(prev.get("ema_trend")):
                prev_ema = float(prev.get("ema_trend"))
            elif "ema21" in prev.index:
                prev_ema = float(prev.get("ema21") or ema_val)
            if prev_ema is not None and ema_val <= prev_ema:
                return None

        min_dist = float(p.get("ema_min_dist_pct") or 0.0)
        if min_dist > 0 and ((close - ema_val) / max(ema_val, 1) * 100) < min_dist:
            return None

        buffer = close * (float(p["breakout_buffer_pct"]) / 100)
        if close <= or_high + buffer:
            return None
        if bool(p.get("require_high_break")) and high <= or_high:
            return None

        body_min = float(p.get("candle_body_min") or 0.0)
        if body_min > 0:
            rng = max(high - low, 0.01)
            body = abs(close - open_px)
            if body / rng < body_min:
                return None

        retest_mode = str(p.get("retest_mode") or "off")
        if retest_mode == "require":
            # Require a prior breakout bar and current close reclaiming OR high from a pullback.
            if idx < 2:
                return None
            earlier = df.iloc[idx - 2]
            if float(earlier["close"]) <= or_high:
                return None
            if float(row["low"]) > or_high:
                return None

        stop_method = str(p.get("stop_method") or "or_mid")
        atr = float(row.get("atr") or close * 0.01)
        if stop_method == "or_low":
            stop = round(or_low, 2)
        elif stop_method == "pct":
            stop = round(close * (1 - float(p.get("stop_pct") or 0.4) / 100), 2)
        elif stop_method == "atr":
            stop = round(close - atr * float(p.get("stop_atr_mult") or 1.0), 2)
        else:
            stop = round((or_high + or_low) / 2, 2)

        risk = close - stop
        max_risk = close * (float(p["max_risk_pct"]) / 100)
        if risk <= 0 or risk > max_risk:
            return None
        target = round(close + float(p["min_rr"]) * risk, 2)
        trail = None
        if float(p.get("trail_after_r") or 0) > 0 and float(p.get("trail_atr_mult") or 0) > 0:
            # Percentage trail approx from ATR distance.
            trail = round(atr * float(p["trail_atr_mult"]) / max(close, 1) * 100, 4)

        return IntradaySignal(
            side="BUY",
            entry=close,
            stoploss=stop,
            target=target,
            trailing_pct=trail,
            strategy_id=self.id,
            strategy_code=self.code,
        )

    def try_exit(self, position: dict, df: pd.DataFrame, idx: int) -> tuple[float, str] | None:
        row = df.iloc[idx]
        side = position["side"]
        # Optional activate trailing after R multiple.
        trail_after = float(self.params.get("trail_after_r") or 0)
        if trail_after > 0 and position.get("trailing_pct"):
            entry = float(position["entry_price"])
            stop0 = float(position.get("initial_stoploss") or position["stoploss"])
            risk = abs(entry - stop0)
            if risk > 0:
                fav = (float(row["close"]) - entry) if side == "BUY" else (entry - float(row["close"]))
                if fav >= trail_after * risk:
                    self.update_trailing(position, row)

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
