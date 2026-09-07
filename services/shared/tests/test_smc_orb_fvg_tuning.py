"""Tests for SMC ORB + FVG tuning defaults (Nifty SCALP-SMC-003; Bank SMC-006 removed)."""

from trading_shared.strategies.scalping_desk.smc_orb_fvg_tuning import (
    SMC_ORB_FVG_BANK_DEFAULTS,
    SMC_ORB_FVG_NIFTY_DEFAULTS,
    merge_smc_orb_fvg_params,
)
from trading_shared.strategies.scalping_desk.strategy_catalog import CATALOG_VERSION, normalize_desk_config


def test_merge_smc_orb_fvg_bank_defaults():
    merged = merge_smc_orb_fvg_params({}, "banknifty")
    assert merged["smc_orb_require_fvg"] is False
    assert merged["volume_min"] == 1.15
    assert merged["smc_orb_stop_pts"] == SMC_ORB_FVG_BANK_DEFAULTS["smc_orb_stop_pts"]


def test_merge_smc_orb_fvg_nifty_volume_and_or_floor():
    merged = merge_smc_orb_fvg_params({}, "nifty50")
    assert merged["volume_min"] == 1.15
    assert merged["smc_orb_range_min"] == 40.0
    assert merged["volume_min"] == SMC_ORB_FVG_NIFTY_DEFAULTS["volume_min"]
    assert merged["smc_orb_range_min"] == SMC_ORB_FVG_NIFTY_DEFAULTS["smc_orb_range_min"]


def test_normalize_bank_drops_smc_params():
    saved = {"catalog_version": 8, "smc_params": {"smc_orb_require_momentum": False}, "params": {}}
    cfg = normalize_desk_config(saved, "banknifty")
    assert cfg["catalog_version"] == CATALOG_VERSION
    assert "smc_params" not in cfg


def test_normalize_nifty_includes_orb_fvg_params():
    saved = {"catalog_version": 8, "smc_params": {"smc_orb_require_momentum": False}, "params": {}}
    cfg = normalize_desk_config(saved, "nifty50")
    assert cfg["catalog_version"] == CATALOG_VERSION
    smc = cfg["smc_params"]
    assert smc["smc_orb_require_fvg"] == SMC_ORB_FVG_NIFTY_DEFAULTS["smc_orb_require_fvg"]
