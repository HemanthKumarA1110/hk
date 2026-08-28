"""Unit tests for INTRA-VWAP-ORB (VwapOrbTrendFilter / VWAP_ORB_TrendFilter)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from trading_shared.strategies.intraday_desk.session import enrich_for_strategy
from trading_shared.strategies.intraday_desk.strategies.vwap_orb_trend import (
    ATR_STOP_MULT,
    VwapOrbTrendFilter,
)


def test_stoploss_prefers_tighter_of_atr_and_or():
    s = VwapOrbTrendFilter()
    # Long: ATR stop below entry; OR low closer → use OR low.
    entry, atr, or_high, or_low = 100.0, 2.0, 99.5, 98.5
    atr_stop = entry - ATR_STOP_MULT * atr  # 97.0
    stop = s.stoploss_price("BUY", entry, atr, or_high, or_low)
    assert stop == or_low
    assert stop > atr_stop

    # Short: ATR stop above; OR high closer → use OR high.
    entry, atr, or_high, or_low = 100.0, 2.0, 101.5, 98.0
    atr_stop = entry + ATR_STOP_MULT * atr  # 103.0
    stop = s.stoploss_price("SELL", entry, atr, or_high, or_low)
    assert stop == or_high
    assert stop < atr_stop


def test_circuit_breaker_after_two_consecutive_stops():
    s = VwapOrbTrendFilter()
    day = datetime(2025, 1, 6).date()
    s.on_trade_closed(day=day, exit_reason="stoploss")
    assert s._entries_disabled is False
    s.on_trade_closed(day=day, exit_reason="stoploss")
    assert s._entries_disabled is True
    # Winning trade resets consecutive stops but same-day disable stays until next day.
    s.on_trade_closed(day=day, exit_reason="trail_ema")
    assert s._consec_stops == 0
    assert s._entries_disabled is True
    # New day clears disable.
    s._roll_day(datetime(2025, 1, 7, 10, 0))
    assert s._entries_disabled is False


def test_entry_helpers_and_backtest_enrich():
    rows = []
    t = datetime(2025, 1, 6, 9, 15)
    price = 100.0
    for i in range(60):
        close = price + i * 0.4
        rows.append(
            {
                "timestamp": t,
                "open": close - 0.1,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 20000 if i < 20 else 50000,
            }
        )
        t += timedelta(minutes=5)
        price = close
    df = enrich_for_strategy(pd.DataFrame(rows), "INTRA-VWAP-ORB")
    assert "vol_avg10" in df.columns
    assert "ema9" in df.columns and "ema21" in df.columns
    s = VwapOrbTrendFilter()
    pos = {
        "side": "BUY",
        "entry_price": 110.0,
        "stoploss": 108.0,
        "initial_stoploss": 108.0,
        "highest_price": 110.0,
        "scaled_out": False,
        "breakeven_moved": False,
    }
    # Smoke: helpers match try_* interface and do not crash.
    _ = s.entry_signal(df, 30, traded_today=False)
    exit_hit = s.exit_signal(pos, df, 40)
    assert exit_hit is None or isinstance(exit_hit, tuple)
