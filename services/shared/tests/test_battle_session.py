"""Tests for fixed battle session windows."""

from __future__ import annotations

from trading_shared.strategies.scalping_desk.battle_tested_scalp import (
    evaluate_battle_session,
    in_battle_session,
    precompute_battle_session_mask,
)
from zoneinfo import ZoneInfo
import pandas as pd


def test_in_battle_session_morning_window():
    assert in_battle_session("2026-07-09T09:25:00+05:30") is True


def test_in_battle_session_afternoon_window():
    assert in_battle_session("2026-07-09T14:00:00+05:30") is True


def test_in_battle_session_outside_windows():
    assert in_battle_session("2026-07-09T11:30:00+05:30") is False
    assert in_battle_session("2026-07-09T09:15:00+05:30") is False


def test_in_battle_session_uses_wall_clock_when_bar_is_stale():
    stale = "2026-07-10T12:06:00+05:30"
    assert in_battle_session(stale) is False
    # Afternoon window should still open when the cached bar timestamp is stale.
    from unittest.mock import patch
    from datetime import datetime

    afternoon = datetime(2026, 7, 10, 14, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    with patch("trading_shared.strategies.scalping_desk.battle_tested_scalp.datetime") as mock_dt:
        mock_dt.now.return_value = afternoon
        assert in_battle_session(stale) is True


def test_precompute_battle_session_mask_ignores_wall_clock():
    df = pd.DataFrame({"timestamp": ["2026-06-01T09:25:00+05:30", "2026-06-01T11:00:00+05:30"]})
    mask = precompute_battle_session_mask(df, "nifty50")
    assert mask == [True, False]


def test_in_battle_session_weekend():
    assert in_battle_session("2026-07-11T10:00:00+05:30") is False


def test_evaluate_battle_session_structure():
    result = evaluate_battle_session("2026-07-09T10:00:00+05:30", instrument_key="banknifty")
    assert result["session_ok"] is True
    assert result["mode"] == "battle_windows"
    assert result["active_window"] == "09:20–10:30"


def test_precompute_battle_session_mask():
    df = pd.DataFrame(
        {
            "timestamp": [
                "2026-07-09T09:25:00+05:30",
                "2026-07-09T11:00:00+05:30",
                "2026-07-09T13:45:00+05:30",
            ]
        }
    )
    mask = precompute_battle_session_mask(df, "nifty50")
    assert mask == [True, False, True]
