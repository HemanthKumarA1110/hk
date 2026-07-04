"""Tests for unified scalping strategy catalog."""

from trading_shared.strategies.scalping_desk.strategy_catalog import (
    CATALOG_VERSION,
    STRATEGY_CATALOG,
    catalog_for_api,
    catalog_for_instrument,
    code_for_id,
    default_strategy_settings,
    enabled_codes,
    merge_strategy_settings,
    normalize_desk_config,
    resolve_strategy_code,
)


def test_catalog_has_unique_codes():
    codes = list(STRATEGY_CATALOG.keys())
    assert len(codes) == len(set(codes))
    assert all(code.startswith("SCALP-") for code in codes)


def test_nifty_has_eight_strategies_banknifty_has_nine():
    nifty = catalog_for_instrument("nifty50")
    bank = catalog_for_instrument("banknifty")
    assert len(nifty) == 8
    assert len(bank) == 9
    assert any(s["code"] == "SCALP-BT-002" for s in bank)
    assert not any(s["code"] == "SCALP-BT-002" for s in nifty)


def test_default_settings_enable_battle_paper():
    nifty = default_strategy_settings("nifty50")
    assert nifty["SCALP-BT-001"]["enabled"] is True
    assert nifty["SCALP-BT-001"]["execution_mode"] == "paper"
    assert nifty["SCALP-BT-002"]["enabled"] is False

    bank = default_strategy_settings("banknifty")
    assert bank["SCALP-BT-001"]["enabled"] is True
    assert bank["SCALP-BT-002"]["enabled"] is True


def test_merge_adds_new_catalog_entries():
    saved = {"SCALP-BT-001": {"enabled": True, "execution_mode": "live"}}
    merged = merge_strategy_settings({"strategy_settings": saved}, "nifty50")
    assert merged["SCALP-BT-001"]["execution_mode"] == "live"
    assert "SCALP-AD-001" in merged


def test_normalize_syncs_legacy_fixed_id():
    cfg = normalize_desk_config(
        {"fixed_strategy_id": "ema_crossover_rsi", "strategy_mode": "manual"},
        "nifty50",
    )
    assert cfg["fixed_strategy_code"] == "SCALP-BT-001"
    assert cfg["catalog_version"] == CATALOG_VERSION


def test_resolve_strategy_code_from_selection():
    code = resolve_strategy_code(
        selection={"selected_strategy_code": "SCALP-SMC-001"},
        signal={"strategy_id": "smc_fvg_ob_bos"},
    )
    assert code == "SCALP-SMC-001"


def test_code_for_id_roundtrip():
    assert code_for_id("orb_breakout") == "SCALP-BT-002"
    assert code_for_id("momentum_burst") == "SCALP-AD-001"


def test_catalog_for_api_includes_settings():
    rows = catalog_for_api("nifty50", {"strategy_settings": {"SCALP-BT-001": {"enabled": True, "execution_mode": "live"}}})
    bt1 = next(r for r in rows if r["code"] == "SCALP-BT-001")
    assert bt1["enabled"] is True
    assert bt1["execution_mode"] == "live"


def test_enabled_codes():
    cfg = {"strategy_settings": {"SCALP-BT-001": {"enabled": True, "execution_mode": "paper"}, "SCALP-AD-001": {"enabled": False, "execution_mode": "paper"}}}
    assert enabled_codes(cfg, "nifty50") == ["SCALP-BT-001"]


def test_run_strategy_backtest_unknown_code():
    import pandas as pd

    from trading_shared.strategies.scalping_desk.backtest import run_strategy_backtest

    empty = pd.DataFrame()
    result = run_strategy_backtest(empty, "1m", 25, 100000, strategy_code="SCALP-XX-999", instrument_key="nifty50")
    assert result["total_trades"] == 0
    assert "Unknown" in (result.get("message") or "")
