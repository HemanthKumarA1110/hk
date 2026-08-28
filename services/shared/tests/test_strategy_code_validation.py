"""Tests for desk-scoped strategy code validation."""

import pytest

from trading_shared.strategies.equity_strategy_catalog import catalog_for_engine
from trading_shared.strategies.scalping_desk.strategy_catalog import catalog_for_api
from trading_shared.strategies.strategy_code_validation import (
    desk_for_strategy_code,
    filter_catalog_for_engine,
    validate_strategy_code_for_engine,
)


def test_desk_for_strategy_code():
    assert desk_for_strategy_code("SCALP-AD-002") == "scalping"
    assert desk_for_strategy_code("INTRA-ORB") == "intraday"
    assert desk_for_strategy_code("SWING-EMA") == "swing"
    assert desk_for_strategy_code("UNKNOWN") is None


def test_validate_accepts_matching_desk():
    validate_strategy_code_for_engine("intraday", "INTRA-ORB")
    validate_strategy_code_for_engine("swing", "SWING-EMA")
    validate_strategy_code_for_engine("scalping", "SCALP-AD-002")


def test_validate_rejects_cross_desk():
    with pytest.raises(ValueError, match="belongs to scalping, not intraday"):
        validate_strategy_code_for_engine("intraday", "SCALP-AD-002")
    with pytest.raises(ValueError, match="belongs to intraday, not swing"):
        validate_strategy_code_for_engine("swing", "INTRA-ORB")
    with pytest.raises(ValueError, match="belongs to swing, not scalping"):
        validate_strategy_code_for_engine("scalping", "SWING-EMA")


def test_filter_catalog_for_engine_intraday():
    rows = catalog_for_engine("intraday")
    filtered = filter_catalog_for_engine("intraday", rows)
    assert filtered
    assert all(r["code"].startswith("INTRA-") for r in filtered)


def test_filter_catalog_for_engine_scalping():
    rows = catalog_for_api("nifty50", {})
    filtered = filter_catalog_for_engine("scalping", rows)
    assert filtered
    assert all(r["code"].startswith("SCALP-") for r in filtered)
