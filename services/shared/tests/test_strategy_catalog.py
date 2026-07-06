"""Tests for unified scalping strategy catalog."""

from trading_shared.strategies.scalping_desk.strategy_catalog import (
    BANK_NIFTY_LEGACY_CODE_MAP,
    CATALOG_VERSION,
    STRATEGY_CATALOG,
    catalog_for_api,
    catalog_for_instrument,
    code_for_id,
    default_fixed_strategy_code,
    default_strategy_settings,
    enabled_codes,
    merge_strategy_settings,
    migrate_bank_strategy_code,
    normalize_desk_config,
    resolve_strategy_code,
)


def test_catalog_has_unique_codes():
    codes = list(STRATEGY_CATALOG.keys())
    assert len(codes) == len(set(codes))
    assert all(code.startswith("SCALP-") for code in codes)


def test_nifty_and_bank_have_separate_strategy_sets():
    nifty = catalog_for_instrument("nifty50")
    bank = catalog_for_instrument("banknifty")
    assert len(nifty) == 8
    assert len(bank) == 9
    assert not any(s["code"] == "SCALP-BT-002" for s in nifty)
    assert not any(s["code"] == "SCALP-BT-001" for s in bank)
    assert any(s["code"] == "SCALP-BT-003" for s in bank)
    assert any(s["code"] == "SCALP-AD-005" for s in bank)


def test_default_settings_enable_battle_paper():
    nifty = default_strategy_settings("nifty50")
    assert nifty["SCALP-BT-001"]["enabled"] is True
    assert nifty["SCALP-BT-001"]["execution_mode"] == "paper"
    assert "SCALP-BT-002" not in nifty

    bank = default_strategy_settings("banknifty")
    assert bank["SCALP-BT-003"]["enabled"] is True
    assert bank["SCALP-BT-002"]["enabled"] is True
    assert bank["SCALP-AD-007"]["enabled"] is False


def test_merge_adds_new_catalog_entries():
    saved = {"SCALP-BT-001": {"enabled": True, "execution_mode": "live"}}
    merged = merge_strategy_settings({"strategy_settings": saved}, "nifty50")
    assert merged["SCALP-BT-001"]["execution_mode"] == "live"
    assert "SCALP-AD-001" in merged


def test_merge_migrates_legacy_bank_codes():
    saved = {
        "SCALP-BT-001": {"enabled": True, "execution_mode": "live"},
        "SCALP-AD-001": {"enabled": True, "execution_mode": "paper"},
    }
    merged = merge_strategy_settings({"strategy_settings": saved}, "banknifty")
    assert merged["SCALP-BT-003"]["enabled"] is True
    assert merged["SCALP-BT-003"]["execution_mode"] == "live"
    assert merged["SCALP-AD-005"]["enabled"] is True
    assert "SCALP-BT-001" not in merged


def test_normalize_syncs_legacy_fixed_id():
    cfg = normalize_desk_config(
        {"fixed_strategy_id": "ema_crossover_rsi", "strategy_mode": "manual"},
        "nifty50",
    )
    assert cfg["fixed_strategy_code"] == "SCALP-BT-001"
    assert cfg["catalog_version"] == CATALOG_VERSION

    bank_cfg = normalize_desk_config(
        {"fixed_strategy_id": "ema_crossover_rsi", "strategy_mode": "manual"},
        "banknifty",
    )
    assert bank_cfg["fixed_strategy_code"] == "SCALP-BT-003"


def test_resolve_strategy_code_from_selection():
    code = resolve_strategy_code(
        selection={"selected_strategy_code": "SCALP-SMC-001"},
        signal={"strategy_id": "smc_fvg_ob_bos"},
    )
    assert code == "SCALP-SMC-001"


def test_code_for_id_is_instrument_aware():
    assert code_for_id("orb_breakout") == "SCALP-BT-002"
    assert code_for_id("momentum_burst", "nifty50") == "SCALP-AD-001"
    assert code_for_id("momentum_burst", "banknifty") == "SCALP-AD-005"
    assert code_for_id("ema_crossover_rsi", "banknifty") == "SCALP-BT-003"


def test_default_fixed_strategy_code():
    assert default_fixed_strategy_code("nifty50") == "SCALP-BT-001"
    assert default_fixed_strategy_code("banknifty") == "SCALP-BT-003"


def test_migrate_bank_strategy_code():
    assert migrate_bank_strategy_code("SCALP-AD-001", "banknifty") == "SCALP-AD-005"
    assert migrate_bank_strategy_code("SCALP-AD-001", "nifty50") == "SCALP-AD-001"
    assert len(BANK_NIFTY_LEGACY_CODE_MAP) == 8


def test_catalog_for_api_includes_settings():
    rows = catalog_for_api("nifty50", {"strategy_settings": {"SCALP-BT-001": {"enabled": True, "execution_mode": "live"}}})
    bt1 = next(r for r in rows if r["code"] == "SCALP-BT-001")
    assert bt1["enabled"] is True
    assert bt1["execution_mode"] == "live"


def test_enabled_codes():
    cfg = {"strategy_settings": {"SCALP-BT-001": {"enabled": True, "execution_mode": "paper"}, "SCALP-AD-001": {"enabled": False, "execution_mode": "paper"}}}
    assert enabled_codes(cfg, "nifty50") == ["SCALP-BT-001"]


def test_normalize_resets_stale_bank_ema_params():
    saved = {
        "catalog_version": 2,
        "params": {
            "ema_crossover": {
                "ema_vol_min": 1.2,
                "ema_use_vol_spike": True,
                "ema_min_separation_pct": 0.03,
                "ema_rsi_call_min": 50,
            }
        },
    }
    cfg = normalize_desk_config(saved, "banknifty")
    assert cfg["catalog_version"] == CATALOG_VERSION
    ema = cfg["params"]["ema_crossover"]
    assert ema["ema_vol_min"] == 0.0
    assert ema["ema_rsi_call_min"] == 53
    assert ema["ema_rsi_call_max"] == 60


def test_run_strategy_backtest_unknown_code():
    import pandas as pd

    from trading_shared.strategies.scalping_desk.backtest import run_strategy_backtest

    empty = pd.DataFrame()
    result = run_strategy_backtest(empty, "1m", 25, 100000, strategy_code="SCALP-XX-999", instrument_key="nifty50")
    assert result["total_trades"] == 0
    assert "Unknown" in (result.get("message") or "")

    wrong_desk = run_strategy_backtest(
        empty, "1m", 15, 100000, strategy_code="SCALP-AD-001", instrument_key="banknifty"
    )
    assert wrong_desk["total_trades"] == 0
