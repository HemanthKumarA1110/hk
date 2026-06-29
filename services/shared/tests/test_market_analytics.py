import pytest
from datetime import datetime, timezone

from trading_shared.market.analytics import compute_pcr, compute_vwap, detect_gap, normalize_price, parse_tick


def test_normalize_price():
    assert normalize_price(24567) == 245.67


def test_vwap():
    assert compute_vwap([100, 110], [10, 20]) == pytest.approx(106.666, rel=1e-3)


def test_gap_detection():
    gap = detect_gap(105, 100, threshold_pct=1)
    assert gap["gap_type"] == "gap_up"


def test_pcr():
    assert compute_pcr(1000, 1200) == 1.2


def test_parse_tick():
    tick = parse_tick({"token": "3045", "last_traded_price": 50000, "exchange_type": 1})
    assert tick["ltp"] == 500.0
    assert tick["token"] == "3045"
