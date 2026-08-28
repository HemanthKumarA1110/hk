from datetime import datetime
from zoneinfo import ZoneInfo

from trading_shared.strategies.scalping_desk.expiry_day_handler import (
    expiry_allows_signal,
    expiry_blocks_new_entries,
    handle_expiry_day,
    hours_to_expiry,
    is_banknifty_expiry_day,
    is_instrument_expiry_day,
    is_last_thursday,
    is_nifty_expiry_day,
    last_thursday,
)

IST = ZoneInfo("Asia/Kolkata")


def _dt(y, m, d, h=10, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=IST)


def test_nifty_expiry_thursday():
    assert is_nifty_expiry_day(_dt(2026, 6, 4)) is True
    assert is_nifty_expiry_day(_dt(2026, 6, 3)) is False


def test_banknifty_expiry_wednesday():
    assert is_banknifty_expiry_day(_dt(2026, 6, 3)) is True
    assert is_banknifty_expiry_day(_dt(2026, 6, 4)) is False


def test_last_thursday_june_2026():
    assert last_thursday(2026, 6).day == 25
    assert is_last_thursday(_dt(2026, 6, 25)) is True


def test_before_11_no_trades():
    out = handle_expiry_day("nifty50", _dt(2026, 6, 4, 9, 30))
    assert out["is_expiry"] is True
    assert out["recommended_window"] == "none"
    assert out["max_trades"] == 0
    assert expiry_blocks_new_entries(out) is True


def test_mid_session_trend_sl():
    out = handle_expiry_day("banknifty", _dt(2026, 6, 3, 12, 0), trend_direction="up")
    assert out["recommended_window"] == "11-13"
    assert out["sl_multiplier"] == 1.4
    assert out["max_trades"] == 2
    assert out["allowed_directions"] == "long_only"
    assert expiry_blocks_new_entries(out) is False


def test_after_13_no_new():
    out = handle_expiry_day("nifty50", _dt(2026, 6, 4, 14, 0))
    assert out["recommended_window"] == "avoid"
    assert out["max_trades"] == 0
    assert expiry_blocks_new_entries(out) is True


def test_non_expiry_full_session():
    out = handle_expiry_day("nifty50", _dt(2026, 6, 2, 10, 0))
    assert out["is_expiry"] is False
    assert out["max_trades"] == 3
    assert out["recommended_window"] == "full"


def test_expiry_allows_trend_call():
    handler = handle_expiry_day("nifty50", _dt(2026, 6, 4, 12, 0), trend_direction="up")
    assert expiry_allows_signal(handler, "CALL", trend_direction="up") is True
    assert expiry_allows_signal(handler, "PUT", trend_direction="up") is False


def test_hours_to_expiry():
    hrs = hours_to_expiry(_dt(2026, 6, 4, 12, 0))
    assert 3.0 <= hrs <= 4.0


def test_expiry_am_does_not_emit_max_trades_ceiling_alert():
    from trading_shared.strategies.scalping_desk.guards import guard_status

    expiry = handle_expiry_day("nifty50", _dt(2026, 6, 4, 9, 40))
    status = guard_status(
        {"trades_today": 0, "daily_pnl": 0, "stream_connected": True},
        {"max_trades_per_day": 3, "max_loss_per_day": 5000, "auto_trading_enabled": True},
        expiry_handler=expiry,
    )
    assert status["can_enter"] is False
    assert any("Expiry AM" in a for a in status["alerts"])
    assert not any("Max trades ceiling" in a for a in status["alerts"])
    assert status["trades_capped"] is False


def test_expiry_restrictions_toggle_disables_blocks():
    from trading_shared.strategies.scalping_desk.expiry_day_handler import apply_expiry_restriction_toggle

    blocked = handle_expiry_day("nifty50", _dt(2026, 6, 4, 9, 30))
    assert expiry_blocks_new_entries(blocked) is True
    off = apply_expiry_restriction_toggle(blocked, enabled=False, default_max_trades=5)
    assert off["restrictions_enabled"] is False
    assert off["is_expiry"] is True
    assert off["recommended_window"] == "full"
    assert off["max_trades"] == 5
    assert off["sl_multiplier"] == 1.0
    assert expiry_blocks_new_entries(off) is False
    assert expiry_allows_signal(off, "PUT", trend_direction="up") is True


def test_expiry_restrictions_toggle_keeps_blocks_when_on():
    from trading_shared.strategies.scalping_desk.expiry_day_handler import apply_expiry_restriction_toggle

    blocked = handle_expiry_day("nifty50", _dt(2026, 6, 4, 14, 0))
    on = apply_expiry_restriction_toggle(blocked, enabled=True, default_max_trades=5)
    assert on["restrictions_enabled"] is True
    assert expiry_blocks_new_entries(on) is True
    assert expiry_allows_signal(on, "CALL") is False
