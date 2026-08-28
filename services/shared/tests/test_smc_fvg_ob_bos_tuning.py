"""Tests for SMC FVG + OB + BOS tuning defaults (Nifty SCALP-SMC-001)."""

from trading_shared.strategies.scalping_desk.smc_orb_fvg_tuning import SMC_ORB_FVG_BANK_DEFAULTS
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


def test_normalize_bank_smc_params_use_orb_fvg_defaults():
    """Bank Nifty desks only keep SMC-006 (ORB+FVG); FVG+OB+BOS clone was removed."""
    saved = {
        "catalog_version": 5,
        "smc_params": {"volume_min": 1.2, "fvg_require_bos": False, "fvg_target_pts": 110.0},
        "params": {},
    }
    cfg = normalize_desk_config(saved, "banknifty")
    assert cfg["catalog_version"] == CATALOG_VERSION
    smc = cfg["smc_params"]
    assert smc["volume_min"] == SMC_ORB_FVG_BANK_DEFAULTS["volume_min"]
    assert smc["smc_entry_scan_every"] == SMC_ORB_FVG_BANK_DEFAULTS["smc_entry_scan_every"]
    assert smc["smc_orb_rsi_put_min"] == SMC_ORB_FVG_BANK_DEFAULTS["smc_orb_rsi_put_min"]
    assert smc["smc_orb_momentum_mode"] == SMC_ORB_FVG_BANK_DEFAULTS["smc_orb_momentum_mode"]
