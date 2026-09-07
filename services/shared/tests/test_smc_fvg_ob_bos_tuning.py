"""Tests for SMC FVG + OB + BOS tuning defaults (Nifty SCALP-SMC-001; Bank SMC clones removed)."""

from trading_shared.strategies.scalping_desk.smc_fvg_ob_bos_tuning import (
    merge_smc_fvg_ob_bos_params,
)
from trading_shared.strategies.scalping_desk.strategy_catalog import CATALOG_VERSION, normalize_desk_config


def test_merge_smc_fvg_bank_defaults():
    merged = merge_smc_fvg_ob_bos_params({})
    assert merged["fvg_require_bos"] is True
    assert merged["volume_min"] == 1.15
    assert merged["fvg_stop_pts"] == 50.0


def test_normalize_bank_drops_smc_after_smc006_removal():
    """Bank Nifty no longer ships SMC catalog strategies; smc_params are dropped."""
    saved = {
        "catalog_version": 5,
        "smc_params": {"volume_min": 1.2, "fvg_require_bos": False, "fvg_target_pts": 110.0},
        "params": {},
    }
    cfg = normalize_desk_config(saved, "banknifty")
    assert cfg["catalog_version"] == CATALOG_VERSION
    assert "smc_params" not in cfg
    assert "SCALP-SMC-006" not in (cfg.get("strategy_settings") or {})
