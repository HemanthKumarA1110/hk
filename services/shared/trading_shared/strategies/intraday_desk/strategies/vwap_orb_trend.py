"""VWAP + Opening Range breakout with EMA trend filter (INTRA-VWAP-ORB).

Class name: VwapOrbTrendFilter (prompt: VWAP_ORB_TrendFilter).
Matches the shared IntradayStrategy interface (try_entry / try_exit).
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from trading_shared.strategies.intraday_desk.intra_vwap_orb_tuning import (
    INTRA_VWAP_ORB_DEFAULTS,
    merge_intra_vwap_orb_params,
    minutes_to_time,
)
from trading_shared.strategies.intraday_desk.session import (
    bar_time,
    is_entry_window,
    is_force_exit_bar,
    trading_date,
)
from trading_shared.strategies.intraday_desk.strategies.base import IntradaySignal, IntradayStrategy

# Module-level aliases (tests / docs) — prefer INTRA_VWAP_ORB_DEFAULTS for live defaults.
EMA_FAST = int(INTRA_VWAP_ORB_DEFAULTS["ema_fast"])
EMA_SLOW = int(INTRA_VWAP_ORB_DEFAULTS["ema_slow"])
ATR_PERIOD = int(INTRA_VWAP_ORB_DEFAULTS["atr_period"])
VOL_LOOKBACK = int(INTRA_VWAP_ORB_DEFAULTS["vol_lookback"])
VOL_MULT = float(INTRA_VWAP_ORB_DEFAULTS["vol_mult"])
ATR_STOP_MULT = float(INTRA_VWAP_ORB_DEFAULTS["atr_stop_mult"])
BREAKEVEN_ATR_MULT = float(INTRA_VWAP_ORB_DEFAULTS["breakeven_atr_mult"])
SCALE_OUT_R = float(INTRA_VWAP_ORB_DEFAULTS["scale_out_r"])
RISK_PCT = float(INTRA_VWAP_ORB_DEFAULTS["risk_pct"])
MAX_TRADES_PER_DAY = int(INTRA_VWAP_ORB_DEFAULTS["max_trades_per_day"])
MAX_CONSEC_STOPS = int(INTRA_VWAP_ORB_DEFAULTS["max_consec_stops"])
OR_END = minutes_to_time(int(INTRA_VWAP_ORB_DEFAULTS["or_end_min"]))
ENTRY_START = minutes_to_time(int(INTRA_VWAP_ORB_DEFAULTS["entry_start_min"]))
ENTRY_END = minutes_to_time(int(INTRA_VWAP_ORB_DEFAULTS["entry_end_min"]))
FORCE_EXIT = minutes_to_time(int(INTRA_VWAP_ORB_DEFAULTS["force_exit_min"]))


class VwapOrbTrendFilter(IntradayStrategy):
    """5m VWAP + OR breakout with EMA trend filter and ATR risk."""

    id = "vwap_orb"
    code = "INTRA-VWAP-ORB"

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        p = merge_intra_vwap_orb_params(params)
        self.params = p
        self.ema_fast = int(p["ema_fast"])
        self.ema_slow = int(p["ema_slow"])
        self.atr_period = int(p["atr_period"])
        self.vol_lookback = int(p["vol_lookback"])
        self.vol_mult = float(p["vol_mult"])
        self.atr_stop_mult = float(p["atr_stop_mult"])
        self.breakeven_atr_mult = float(p["breakeven_atr_mult"])
        self.scale_out_r = float(p["scale_out_r"])
        self.risk_pct = float(p["risk_pct"])
        self.max_trades_per_day = int(p["max_trades_per_day"])
        self.max_consec_stops = int(p["max_consec_stops"])
        self.long_only = bool(p.get("long_only", False))
        self.or_end = minutes_to_time(int(p["or_end_min"]))
        self.entry_start = minutes_to_time(int(p["entry_start_min"]))
        self.entry_end = minutes_to_time(int(p["entry_end_min"]))
        self.force_exit = minutes_to_time(int(p["force_exit_min"]))

        self._day = None
        self._consec_stops = 0
        self._entries_disabled = False

    def _roll_day(self, ts) -> None:
        day = trading_date(ts)
        if day != self._day:
            self._day = day
            self._consec_stops = 0
            self._entries_disabled = False

    def entry_signal(self, df: pd.DataFrame, idx: int, traded_today: bool = False) -> IntradaySignal | None:
        return self.try_entry(df, idx, traded_today)

    def exit_signal(
        self, position: dict, df: pd.DataFrame, idx: int
    ) -> tuple[float, str] | tuple[float, str, float] | None:
        return self.try_exit(position, df, idx)

    def stoploss_price(
        self,
        side: str,
        entry: float,
        atr: float,
        or_high: float,
        or_low: float,
    ) -> float:
        """Initial stop: ATR stop vs OR edge, whichever is tighter to entry."""
        atr_stop = (
            entry - self.atr_stop_mult * atr if side == "BUY" else entry + self.atr_stop_mult * atr
        )
        if side == "BUY":
            or_stop = float(or_low)
            return max(atr_stop, or_stop) if or_stop < entry else atr_stop
        or_stop = float(or_high)
        return min(atr_stop, or_stop) if or_stop > entry else atr_stop

    def on_trade_closed(self, *, day, exit_reason: str) -> None:
        """Update circuit-breaker state after a position fully closes."""
        if day != self._day:
            self._day = day
            self._consec_stops = 0
            self._entries_disabled = False
        if str(exit_reason).startswith("stoploss") or exit_reason == "stop":
            self._consec_stops += 1
            if self._consec_stops >= self.max_consec_stops:
                self._entries_disabled = True
        else:
            self._consec_stops = 0

    def try_entry(self, df: pd.DataFrame, idx: int, traded_today: bool) -> IntradaySignal | None:
        if idx < max(self.ema_slow, self.vol_lookback, self.atr_period) + 1:
            return None

        row = df.iloc[idx]
        ts = row["timestamp"]
        self._roll_day(ts)

        if is_force_exit_bar(ts, force_exit_time=self.force_exit):
            return None
        if not is_entry_window(ts, self.entry_start, self.entry_end):
            return None
        if bar_time(ts) < self.or_end:
            return None
        if traded_today:
            return None
        if self._entries_disabled:
            return None

        close = float(row["close"])
        atr = float(row.get("atr") or 0)
        if atr <= 0 or close <= 0:
            return None

        ema_fast = float(row.get(f"ema{self.ema_fast}") or 0)
        ema_slow = float(row.get(f"ema{self.ema_slow}") or 0)
        if ema_fast <= 0 or ema_slow <= 0:
            return None
        vwap = float(row.get("vwap") or close)
        or_high = row.get("or_high")
        or_low = row.get("or_low")
        if or_high is None or or_low is None or pd.isna(or_high) or pd.isna(or_low):
            return None
        or_high = float(or_high)
        or_low = float(or_low)
        if or_high <= or_low:
            return None

        vol = float(row["volume"])
        vol_col = f"vol_avg{self.vol_lookback}"
        vol_avg = float(row.get(vol_col) or row.get("vol_avg10") or row.get("vol_avg20") or vol)
        if vol <= vol_avg * self.vol_mult:
            return None

        side: str | None = None
        if close > ema_fast and close > ema_slow and close > vwap and close > or_high:
            side = "BUY"
        elif (
            not self.long_only
            and close < ema_fast
            and close < ema_slow
            and close < vwap
            and close < or_low
        ):
            side = "SELL"
        if side is None:
            return None

        stop = self.stoploss_price(side, close, atr, or_high, or_low)
        risk = abs(close - stop)
        if risk <= 0:
            return None
        if side == "BUY":
            target = round(close + self.scale_out_r * risk, 2)
        else:
            target = round(close - self.scale_out_r * risk, 2)

        return IntradaySignal(
            side=side,
            entry=round(close, 2),
            stoploss=round(stop, 2),
            target=target,
            strategy_id=self.id,
            strategy_code=self.code,
        )

    def try_exit(
        self, position: dict, df: pd.DataFrame, idx: int
    ) -> tuple[float, str] | tuple[float, str, float] | None:
        row = df.iloc[idx]
        side = position["side"]
        entry = float(position["entry_price"])
        stop = float(position["stoploss"])
        initial_stop = float(position.get("initial_stoploss") or stop)
        risk = abs(entry - initial_stop)
        atr = float(row.get("atr") or 0)
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        ema_fast = float(row.get(f"ema{self.ema_fast}") or close)

        if side == "BUY":
            position["highest_price"] = max(float(position.get("highest_price") or entry), high)
            fav = close - entry
        else:
            position["lowest_price"] = min(float(position.get("lowest_price") or entry), low)
            fav = entry - close

        if (
            not position.get("breakeven_moved")
            and atr > 0
            and fav >= self.breakeven_atr_mult * atr
        ):
            if side == "BUY":
                position["stoploss"] = max(float(position["stoploss"]), entry)
            else:
                position["stoploss"] = min(float(position["stoploss"]), entry)
            position["breakeven_moved"] = True
            stop = float(position["stoploss"])

        if side == "BUY" and low <= stop:
            return float(stop), "stoploss"
        if side == "SELL" and high >= stop:
            return float(stop), "stoploss"

        scaled = bool(position.get("scaled_out"))
        if not scaled and risk > 0 and fav >= self.scale_out_r * risk:
            return float(close), f"scale_out_{self.scale_out_r}R", 0.5

        if scaled:
            if side == "BUY" and close < ema_fast:
                return float(close), "trail_ema"
            if side == "SELL" and close > ema_fast:
                return float(close), "trail_ema"

        return None
