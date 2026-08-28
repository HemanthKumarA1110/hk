"""Tests for unified scalping strategy catalog."""

from trading_shared.strategies.scalping_desk.strategy_catalog import (
    BANK_NIFTY_LEGACY_CODE_MAP,
    CATALOG_VERSION,
    NIFTY_REMOVED_CODE_MAP,
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
    assert len(nifty) == 3
    assert len(bank) == 5
    assert {s["code"] for s in nifty} == {"SCALP-BT-004", "SCALP-AD-002", "SCALP-SMC-003"}
    assert not any(s["code"] == "SCALP-BT-002" for s in nifty)
    assert not any(s["code"] == "SCALP-BT-001" for s in nifty)
    assert not any(s["code"] == "SCALP-BT-001" for s in bank)
    assert any(s["code"] == "SCALP-BT-003" for s in bank)
    assert any(s["code"] == "SCALP-AD-005" for s in bank)
    assert not any(s["code"] == "SCALP-AD-007" for s in bank)
    assert not any(s["code"] == "SCALP-SMC-001" for s in nifty)
    assert any(s["code"] == "SCALP-SMC-006" for s in bank)


def test_default_settings_enable_all_remaining():
    nifty = default_strategy_settings("nifty50")
    assert nifty["SCALP-AD-002"]["enabled"] is True
    assert nifty["SCALP-BT-004"]["enabled"] is True
    assert nifty["SCALP-AD-002"]["execution_mode"] == "live"
    assert "SCALP-BT-002" not in nifty
    assert all(row["enabled"] for row in nifty.values())
    assert set(nifty) == {"SCALP-BT-004", "SCALP-AD-002", "SCALP-SMC-003"}

    bank = default_strategy_settings("banknifty")
    assert bank["SCALP-BT-003"]["enabled"] is True
    assert bank["SCALP-BT-002"]["enabled"] is True
    assert bank["SCALP-AD-005"]["enabled"] is True
    assert bank["SCALP-AD-006"]["enabled"] is True
    assert bank["SCALP-SMC-006"]["enabled"] is True
    assert "SCALP-AD-007" not in bank
    assert "SCALP-SMC-004" not in bank


def test_normalize_enables_all_bank_on_v17_migrate():
    cfg = normalize_desk_config(
        {
            "catalog_version": 15,
            "strategy_settings": {
                "SCALP-BT-002": {"enabled": True, "execution_mode": "live"},
                "SCALP-BT-003": {"enabled": True, "execution_mode": "paper"},
                "SCALP-AD-005": {"enabled": False, "execution_mode": "paper"},
            },
        },
        "banknifty",
    )
    assert cfg["catalog_version"] == CATALOG_VERSION
    assert cfg["strategy_settings"]["SCALP-AD-005"]["enabled"] is True
    assert cfg["strategy_settings"]["SCALP-SMC-006"]["enabled"] is True
    assert cfg["strategy_settings"]["SCALP-BT-002"]["execution_mode"] == "live"
    assert cfg["strategy_settings"]["SCALP-BT-003"]["execution_mode"] == "live"
    assert cfg["expiry_restrictions_enabled"] is True


def test_normalize_drops_removed_nifty_strategies():
    cfg = normalize_desk_config(
        {
            "catalog_version": 18,
            "fixed_strategy_code": "SCALP-BT-001",
            "strategy_mode": "manual",
            "strategy_settings": {
                "SCALP-BT-001": {"enabled": True, "execution_mode": "live"},
                "SCALP-AD-001": {"enabled": True, "execution_mode": "paper"},
                "SCALP-AD-002": {"enabled": False, "execution_mode": "paper"},
                "SCALP-SMC-003": {"enabled": True, "execution_mode": "paper"},
            },
        },
        "nifty50",
    )
    assert cfg["catalog_version"] == CATALOG_VERSION
    assert "SCALP-BT-001" not in cfg["strategy_settings"]
    assert "SCALP-AD-001" not in cfg["strategy_settings"]
    assert cfg["strategy_settings"]["SCALP-AD-002"]["enabled"] is True
    assert cfg["strategy_settings"]["SCALP-AD-002"]["execution_mode"] == "live"
    assert cfg["strategy_settings"]["SCALP-SMC-003"]["execution_mode"] == "live"
    assert cfg["strategy_settings"]["SCALP-SMC-003"]["enabled"] is True
    assert cfg["strategy_settings"]["SCALP-BT-004"]["enabled"] is True
    assert cfg["fixed_strategy_code"] == "SCALP-AD-002"
    assert cfg["params"]["orb_breakout"]["orb_or_range_min"] == 45.0
    assert cfg["params"]["orb_breakout"]["orb_prior_mode"] == "off"
    assert cfg["params"]["orb_breakout"]["orb_entry_cutoff_min"] == 14 * 60 + 45
    assert "ema_crossover" not in (cfg.get("params") or {})


def test_merge_adds_new_catalog_entries():
    saved = {"SCALP-AD-002": {"enabled": True, "execution_mode": "live"}}
    merged = merge_strategy_settings({"strategy_settings": saved}, "nifty50")
    assert merged["SCALP-AD-002"]["execution_mode"] == "live"
    assert "SCALP-SMC-003" in merged
    assert "SCALP-BT-001" not in merged


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
        {"fixed_strategy_id": "vwap_bounce", "strategy_mode": "manual"},
        "nifty50",
    )
    assert cfg["fixed_strategy_code"] == "SCALP-AD-002"
    assert cfg["catalog_version"] == CATALOG_VERSION

    # Removed Nifty EMA strategy id falls back to default AD-002.
    cfg_old = normalize_desk_config(
        {"fixed_strategy_id": "ema_crossover_rsi", "strategy_mode": "manual"},
        "nifty50",
    )
    assert cfg_old["fixed_strategy_code"] == "SCALP-AD-002"

    bank_cfg = normalize_desk_config(
        {"fixed_strategy_id": "ema_crossover_rsi", "strategy_mode": "manual"},
        "banknifty",
    )
    assert bank_cfg["fixed_strategy_code"] == "SCALP-BT-003"


def test_resolve_strategy_code_from_selection():
    code = resolve_strategy_code(
        selection={"selected_strategy_code": "SCALP-SMC-003"},
        signal={"strategy_id": "smc_orb_fvg"},
    )
    assert code == "SCALP-SMC-003"


def test_code_for_id_is_instrument_aware():
    assert code_for_id("orb_breakout", "banknifty") == "SCALP-BT-002"
    assert code_for_id("orb_breakout", "nifty50") == "SCALP-BT-004"
    assert code_for_id("momentum_burst", "nifty50") is None
    assert code_for_id("momentum_burst", "banknifty") == "SCALP-AD-005"
    assert code_for_id("ema_crossover_rsi", "banknifty") == "SCALP-BT-003"
    assert code_for_id("vwap_bounce", "nifty50") == "SCALP-AD-002"


def test_default_fixed_strategy_code():
    assert default_fixed_strategy_code("nifty50") == "SCALP-AD-002"
    assert default_fixed_strategy_code("banknifty") == "SCALP-BT-003"


def test_migrate_bank_strategy_code():
    assert migrate_bank_strategy_code("SCALP-AD-001", "banknifty") == "SCALP-AD-005"
    assert migrate_bank_strategy_code("SCALP-BT-001", "nifty50") == "SCALP-AD-002"
    assert migrate_bank_strategy_code("SCALP-AD-001", "nifty50") == "SCALP-AD-002"
    assert len(BANK_NIFTY_LEGACY_CODE_MAP) == 4
    assert len(NIFTY_REMOVED_CODE_MAP) == 6


def test_normalize_drops_removed_bank_strategies():
    cfg = normalize_desk_config(
        {
            "fixed_strategy_code": "SCALP-AD-007",
            "strategy_mode": "manual",
            "strategy_settings": {
                "SCALP-AD-007": {"enabled": True, "execution_mode": "paper"},
                "SCALP-SMC-004": {"enabled": True, "execution_mode": "paper"},
            },
        },
        "banknifty",
    )
    assert "SCALP-AD-007" not in cfg["strategy_settings"]
    assert "SCALP-SMC-004" not in cfg["strategy_settings"]
    assert cfg["fixed_strategy_code"] == "SCALP-BT-003"


def test_catalog_for_api_includes_settings():
    rows = catalog_for_api(
        "nifty50", {"strategy_settings": {"SCALP-AD-002": {"enabled": True, "execution_mode": "live"}}}
    )
    ad2 = next(r for r in rows if r["code"] == "SCALP-AD-002")
    assert ad2["enabled"] is True
    assert ad2["execution_mode"] == "live"


def test_enabled_codes():
    cfg = {
        "strategy_settings": {
            "SCALP-AD-002": {"enabled": True, "execution_mode": "paper"},
            "SCALP-SMC-003": {"enabled": False, "execution_mode": "paper"},
        }
    }
    assert enabled_codes(cfg, "nifty50") == ["SCALP-AD-002"]


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
        empty, "1m", 15, 100000, strategy_code="SCALP-AD-005", instrument_key="nifty50"
    )
    assert wrong_desk["total_trades"] == 0
