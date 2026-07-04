import pandas as pd

from trading_shared.strategies.scalping_desk.trailing_sl_manager import (
    apply_trailing_to_trade,
    manage_trailing_sl,
    stop_level_from_pts,
)


def _trade(entry=100.0, stop_pts=7.0, target_pts=14.0, signal_type="CALL"):
    return {
        "signal_type": signal_type,
        "entry_spot": entry,
        "stop_pts": stop_pts,
        "original_stop_pts": stop_pts,
        "target_pts": target_pts,
    }


def test_breakeven_at_half_target():
    trade = _trade()
    out = manage_trailing_sl(
        instrument_key="nifty50",
        trade=trade,
        current_price=107.0,
        candle={"open": 106, "high": 107.5, "low": 106, "close": 107},
    )
    assert out["action"] in ("TIGHTEN", "HOLD")
    assert out["new_sl"] >= 100.0
    assert out["breakeven_armed"] is True


def test_never_widen_stop():
    trade = _trade()
    trade["trail_stop_level"] = stop_level_from_pts(100, 5, "LONG")
    trade["stop_pts"] = 5
    out = manage_trailing_sl(
        instrument_key="nifty50",
        trade=trade,
        current_price=99.0,
        candle={"open": 99.5, "high": 100, "low": 98.5, "close": 99},
    )
    assert out["stop_pts"] <= 5


def test_exit_when_trail_hit():
    trade = _trade()
    trade["trailing_breakeven"] = True
    trade["trail_stop_level"] = 101.0
    trade["stop_pts"] = 0
    out = manage_trailing_sl(
        instrument_key="nifty50",
        trade=trade,
        current_price=100.5,
        candle={"open": 101, "high": 101, "low": 100.4, "close": 100.5},
    )
    assert out["action"] == "EXIT"


def test_apply_trailing_preserves_original_cap():
    trade = _trade(stop_pts=7)
    trailing = {"stop_pts": 3, "trail_stop_level": 97, "breakeven_armed": True, "action": "TIGHTEN", "reason": "test"}
    updated = apply_trailing_to_trade(trade, trailing)
    assert updated["stop_pts"] == 3
    assert updated["original_stop_pts"] == 7
