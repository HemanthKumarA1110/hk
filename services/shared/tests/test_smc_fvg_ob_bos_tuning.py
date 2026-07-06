"""Tests for SCALP-SMC-004 Bank Nifty tuning defaults."""

from trading_shared.strategies.scalping_desk.smc_fvg_ob_bos_tuning import (
    SMC_FVG_OB_BOS_BANK_DEFAULTS,
    merge_smc_fvg_ob_bos_params,
)
from trading_shared.strategies.scalping_desk.strategy_catalog import CATALOG_VERSION, normalize_desk_config


def test_merge_smc_fvg_bank_defaults():
    merged = merge_smc_fvg_ob_bos_params({})
    assert merged["fvg_require_bos"] is True
    assert merged["volume_min"] == 0.0
    assert merged["fvg_stop_pts"] == 55.0


def test_normalize_resets_stale_bank_smc_params():
    saved = {
        "catalog_version": 5,
        "smc_params": {"volume_min": 1.2, "fvg_require_bos": False, "fvg_target_pts": 110.0},
        "params": {},
    }
    cfg = normalize_desk_config(saved, "banknifty")
    assert cfg["catalog_version"] == CATALOG_VERSION
    smc = cfg["smc_params"]
    assert smc["volume_min"] == 0.0
    assert smc["fvg_require_bos"] is True
    assert smc["fvg_rsi_call_min"] == SMC_FVG_OB_BOS_BANK_DEFAULTS["fvg_rsi_call_min"]
    assert smc["fvg_target_pts"] == 120.0
