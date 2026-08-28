from datetime import datetime
from zoneinfo import ZoneInfo

from trading_shared.market.candle_window import angel_candle_window

IST = ZoneInfo("Asia/Kolkata")


def test_before_market_open_returns_none():
    now = datetime(2026, 8, 19, 9, 12, tzinfo=IST)
    assert angel_candle_window("2026-08-19", "2026-08-19", now=now) is None


def test_today_clamps_to_now():
    now = datetime(2026, 8, 19, 10, 30, tzinfo=IST)
    assert angel_candle_window("2026-08-19", "2026-08-19", now=now) == (
        "2026-08-19 09:15",
        "2026-08-19 10:30",
    )


def test_past_day_uses_full_session():
    now = datetime(2026, 8, 19, 10, 30, tzinfo=IST)
    assert angel_candle_window("2026-06-20", "2026-06-20", now=now) == (
        "2026-06-20 09:15",
        "2026-06-20 15:30",
    )


def test_range_clamps_end_to_today():
    now = datetime(2026, 8, 19, 11, 0, tzinfo=IST)
    assert angel_candle_window("2026-08-18", "2026-08-20", now=now) == (
        "2026-08-18 09:15",
        "2026-08-19 11:00",
    )


def test_future_start_returns_none():
    now = datetime(2026, 8, 19, 11, 0, tzinfo=IST)
    assert angel_candle_window("2026-08-20", "2026-08-20", now=now) is None


def test_classify_rate_limit_and_skip():
    from trading_shared.market.candle_window import (
        angel_rate_limit_wait_sec,
        classify_angel_chunk_error,
    )

    assert classify_angel_chunk_error("Angel One API rate limit exceeded. Wait a minute, then retry.") == "rate_limit"
    assert classify_angel_chunk_error("Access denied because of exceeding access rate") == "rate_limit"
    assert classify_angel_chunk_error("From datetime can't be greater than current datetime") == "skip"
    assert classify_angel_chunk_error("token expired") == "error"
    assert angel_rate_limit_wait_sec(0) == 25.0
    assert angel_rate_limit_wait_sec(4) == 90.0
