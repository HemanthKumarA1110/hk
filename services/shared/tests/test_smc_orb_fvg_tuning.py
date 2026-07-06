"""Tests for SCALP-SMC-006 Bank Nifty tuning defaults."""

from trading_shared.strategies.scalping_desk.smc_orb_fvg_tuning import (
    SMC_ORB_FVG_BANK_DEFAULTS,
    merge_smc_orb_fvg_params,
)
from trading_shared.strategies.scalping_desk.strategy_catalog import CATALOG_VERSION, normalize_desk_config


def test_merge_smc_orb_fvg_bank_defaults():
    merged = merge_smc_orb_fvg_params({})
    assert merged["smc_orb_require_fvg"] is False
    assert merged["volume_min"] == 0.0
    assert merged["smc_orb_stop_pts"] == 50.0


def test_normalize_includes_orb_fvg_params():
    saved = {"catalog_version": 8, "smc_params": {"smc_orb_require_momentum": False}, "params": {}}
    cfg = normalize_desk_config(saved, "banknifty")
    assert cfg["catalog_version"] == CATALOG_VERSION
    smc = cfg["smc_params"]
    assert smc["smc_orb_require_fvg"] is False
    assert smc["smc_orb_range_min"] == SMC_ORB_FVG_BANK_DEFAULTS["smc_orb_range_min"]
