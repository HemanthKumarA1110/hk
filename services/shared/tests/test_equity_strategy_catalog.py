"""Tests for intraday/swing equity strategy catalog."""

from trading_shared.strategies.equity_strategy_catalog import (
    catalog_for_engine,
    confirmation_filter_for_code,
    resolve_strategy_code,
)


def test_intraday_catalog_has_three_modular_strategies():
    rows = catalog_for_engine("intraday")
    codes = [r["code"] for r in rows]
    assert codes == ["INTRA-ORB", "INTRA-VWAP", "INTRA-EMA-RSI"]
    assert len(rows) == 3


def test_swing_catalog_has_three_modular_strategies():
    rows = catalog_for_engine("swing")
    codes = [r["code"] for r in rows]
    assert codes == ["SWING-EMA", "SWING-RSI", "SWING-BO-ATR"]
    assert len(rows) == 3


def test_confirmation_filter_returns_strategy_id():
    assert confirmation_filter_for_code("INTRA-ORB") == "orb"
    assert confirmation_filter_for_code("SWING-EMA") == "ema_trend"
    assert confirmation_filter_for_code("SWING-RSI") == "rsi_mean_reversion"


def test_resolve_unknown_code():
    assert resolve_strategy_code("BAD-CODE") is None
