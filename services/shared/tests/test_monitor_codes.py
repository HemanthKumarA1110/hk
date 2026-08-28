"""Tests for multi-strategy monitor selection (auto=all, manual=enabled)."""

from trading_shared.strategies.scalping_desk.strategy_selector import (
    monitor_codes_for_config,
    priority_try_order,
)


def test_auto_monitors_full_bank_catalog_even_if_some_disabled():
    cfg = {
        "strategy_mode": "auto",
        "strategy_settings": {
            "SCALP-BT-002": {"enabled": True, "execution_mode": "paper"},
            "SCALP-BT-003": {"enabled": False, "execution_mode": "paper"},
            "SCALP-AD-005": {"enabled": False, "execution_mode": "paper"},
        },
    }
    codes = monitor_codes_for_config(cfg, "banknifty")
    assert "SCALP-BT-002" in codes
    assert "SCALP-BT-003" in codes
    assert "SCALP-AD-005" in codes
    assert "SCALP-AD-006" in codes
    assert "SCALP-SMC-006" in codes
    assert len(codes) == 5


def test_manual_monitors_only_enabled_multi_select():
    cfg = {
        "strategy_mode": "manual",
        "strategy_settings": {
            "SCALP-BT-002": {"enabled": True, "execution_mode": "paper"},
            "SCALP-BT-003": {"enabled": True, "execution_mode": "paper"},
            "SCALP-AD-005": {"enabled": False, "execution_mode": "paper"},
            "SCALP-AD-006": {"enabled": False, "execution_mode": "paper"},
            "SCALP-SMC-006": {"enabled": True, "execution_mode": "paper"},
        },
    }
    codes = monitor_codes_for_config(cfg, "banknifty")
    assert set(codes) == {"SCALP-BT-002", "SCALP-BT-003", "SCALP-SMC-006"}
    assert "SCALP-AD-005" not in codes


def test_auto_monitors_full_nifty_catalog():
    cfg = {"strategy_mode": "auto", "strategy_settings": {}}
    codes = monitor_codes_for_config(cfg, "nifty50")
    assert len(codes) == 3
    assert set(codes) == {"SCALP-BT-004", "SCALP-AD-002", "SCALP-SMC-003"}


def test_manual_monitors_only_enabled_nifty():
    settings = {
        "SCALP-BT-004": {"enabled": False, "execution_mode": "paper"},
        "SCALP-AD-002": {"enabled": True, "execution_mode": "paper"},
        "SCALP-SMC-003": {"enabled": False, "execution_mode": "paper"},
    }
    cfg = {
        "strategy_mode": "manual",
        "strategy_settings": settings,
    }
    codes = monitor_codes_for_config(cfg, "nifty50")
    assert set(codes) == {"SCALP-AD-002"}


def test_priority_order_battle_then_adaptive_then_smc():
    order = priority_try_order(
        ["SCALP-SMC-006", "SCALP-AD-005", "SCALP-BT-003", "SCALP-AD-006", "SCALP-BT-002"],
        rankings=[
            {"strategy_id": "vwap_bounce", "score": 90},
            {"strategy_id": "momentum_burst", "score": 40},
        ],
    )
    assert order[:2] == ["SCALP-BT-002", "SCALP-BT-003"]
    assert order[-1] == "SCALP-SMC-006"
    # Adaptive sorted by score — vwap (AD-006) before momentum (AD-005)
    assert order.index("SCALP-AD-006") < order.index("SCALP-AD-005")
