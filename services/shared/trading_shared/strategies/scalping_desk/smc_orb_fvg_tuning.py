"""SMC ORB + FVG parameter defaults (SCALP-SMC-003 Nifty / SCALP-SMC-006 Bank)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from trading_shared.strategies.scalping_desk.smc_scalping_engine import DEFAULT_SMC_PARAMS

# Nifty 50 SMC ORB+FVG — OFAT + WF on Angel One 1m (2026-06-10→08-09).
# Baseline already ~100% WR / small expectancy; retune raises trade count + expectancy.
# fvg_min_gap_pct units: gap/mid*100 >= value (0.008 ≈ near-unfiltered).
# Flag: 100% WR / 0 DD persists OOS — premium-exit model rarely realizes losses; forward-test carefully.
# ATR stop/target/trail were largely insensitive on this sample; values kept from OFAT lock.
SMC_ORB_FVG_NIFTY_DEFAULTS: dict[str, Any] = {
    **DEFAULT_SMC_PARAMS,
    "volume_min": 0.0,
    "orb_minutes": 15,
    "fvg_min_gap_pct": 0.008,
    "entry_buffer_pct": 0.0,
    "stop_atr_mult": 0.7,
    "target_atr_mult": 1.0,
    "trailing_atr_mult": 0.0,
    "max_hold_bars": 6,
    "smc_orb_range_min": 0.0,
    "smc_orb_range_max": 99999.0,
    "smc_orb_skip_wide_or": False,
    "smc_orb_pad_pct": 0.002,
    "smc_orb_breakout_pad_pct": 0.0,
    "smc_orb_entry_start_min": 9 * 60 + 25,
    "smc_orb_entry_cutoff_min": 11 * 60,
    "smc_orb_require_fvg": False,
    "smc_orb_require_breakout": False,
    "smc_orb_require_momentum": False,
    "smc_orb_require_ema_momentum": False,
    "smc_orb_momentum_mode": "off",
    "smc_orb_path_mode": "fvg_or_mom",
    "smc_orb_fvg_retest_mode": "touch",
    "smc_orb_bias_mode": "block_opposite",
    "smc_orb_require_structure": False,
    "smc_orb_rsi_enabled": False,
    "smc_orb_rsi_slope": False,
    "smc_orb_rsi_call_min": 40,
    "smc_orb_rsi_call_max": 70,
    "smc_orb_rsi_put_min": 30,
    "smc_orb_rsi_put_max": 60,
    "smc_orb_ema_sep_pct": 0.0,
    "smc_orb_reject_body_min": 0.5,
    "smc_orb_reject_wick_min": 0.2,
    "smc_orb_reject_body_max": 0.72,
    "smc_orb_reject_mode": "body_or_wick",
    "smc_entry_scan_every": 2,
    "smc_min_bars_between": 3,
    "smc_max_bars": 15000,
}

SMC_ORB_FVG_NIFTY_LEGACY: dict[str, Any] = {
    **DEFAULT_SMC_PARAMS,
    "volume_min": 0.95,
    "orb_minutes": 15,
    "fvg_min_gap_pct": 0.008,
    "entry_buffer_pct": 0.12,
    "stop_atr_mult": 1.0,
    "target_atr_mult": 1.6,
    "trailing_atr_mult": 0.75,
    "max_hold_bars": 12,
    "smc_orb_range_min": 0.0,
    "smc_orb_range_max": 99999.0,
    "smc_orb_skip_wide_or": False,
    "smc_orb_pad_pct": 0.0008,
    "smc_orb_breakout_pad_pct": 0.0,
    "smc_orb_entry_start_min": 9 * 60 + 30,
    "smc_orb_entry_cutoff_min": 10 * 60 + 45,
    "smc_orb_require_fvg": False,
    "smc_orb_require_breakout": False,
    "smc_orb_require_momentum": False,
    "smc_orb_require_ema_momentum": False,
    "smc_orb_momentum_mode": "off",
    "smc_orb_path_mode": "fvg_or_mom",
    "smc_orb_fvg_retest_mode": "touch",
    "smc_orb_bias_mode": "block_opposite",
    "smc_orb_require_structure": False,
    "smc_orb_rsi_enabled": True,
    "smc_orb_rsi_slope": False,
    "smc_orb_rsi_call_min": 40,
    "smc_orb_rsi_call_max": 70,
    "smc_orb_rsi_put_min": 30,
    "smc_orb_rsi_put_max": 60,
    "smc_orb_ema_sep_pct": 0.0,
    "smc_orb_reject_body_min": 0.55,
    "smc_orb_reject_wick_min": 0.28,
    "smc_orb_reject_body_max": 0.72,
    "smc_orb_reject_mode": "body_or_wick",
    "smc_entry_scan_every": 3,
    "smc_min_bars_between": 8,
    "smc_max_bars": 15000,
}

# Bank Nifty SMC ORB+FVG — retuned 60d Angel One 1m (OFAT + focused WF).
# Lifted trade frequency while keeping high WR: scan 1, cutoff 11:00, PUT RSI 32–48,
# 1-bar momentum, min bars between 5. Flag: sample shows 100% WR / 0 DD — forward-test carefully.
SMC_ORB_FVG_BANK_DEFAULTS: dict[str, Any] = {
    **DEFAULT_SMC_PARAMS,
    "volume_min": 0.0,
    "orb_minutes": 15,
    "fvg_min_gap_pct": 0.005,
    "entry_buffer_pct": 0.10,
    "trailing_atr_mult": 0.0,
    "max_hold_bars": 8,
    "smc_orb_range_min": 100.0,
    "smc_orb_range_max": 220.0,
    "smc_orb_skip_wide_or": True,
    "smc_orb_pad_pct": 0.0008,
    "smc_orb_entry_start_min": 9 * 60 + 30,
    "smc_orb_entry_cutoff_min": 11 * 60,
    "smc_orb_require_fvg": False,
    "smc_orb_require_breakout": True,
    "smc_orb_require_momentum": True,
    "smc_orb_momentum_mode": "one_bar",  # two_bar | one_bar | off
    "smc_orb_stop_pts": 50.0,
    "smc_orb_target_pts": 120.0,
    "smc_orb_rsi_call_min": 50,
    "smc_orb_rsi_call_max": 66,
    "smc_orb_rsi_put_min": 32,
    "smc_orb_rsi_put_max": 48,
    "smc_entry_scan_every": 1,
    "smc_min_bars_between": 5,
    "smc_max_bars": 15000,
}

SMC_ORB_FVG_BANK_LEGACY: dict[str, Any] = {
    **DEFAULT_SMC_PARAMS,
    "volume_min": 0.95,
    "smc_orb_range_min": 0.0,
    "smc_orb_range_max": 99999.0,
    "smc_orb_skip_wide_or": False,
    "smc_orb_require_fvg": False,
    "smc_orb_require_breakout": False,
    "smc_orb_require_momentum": False,
}


def merge_smc_orb_fvg_params(
    params: dict[str, Any] | None = None,
    instrument_key: str = "banknifty",
) -> dict[str, Any]:
    base = SMC_ORB_FVG_NIFTY_DEFAULTS if instrument_key == "nifty50" else SMC_ORB_FVG_BANK_DEFAULTS
    merged = dict(base)
    if not params:
        return merged
    nested = params.get("smc_params") if isinstance(params.get("smc_params"), dict) else {}
    if nested:
        merged.update({k: v for k, v in nested.items() if v is not None})
    for key, value in params.items():
        if value is None or key == "smc_params":
            continue
        if key in merged or key.startswith(
            ("smc_orb_", "smc_", "orb_", "fvg_", "entry_", "volume_", "stop_", "target_", "trailing_", "max_hold")
        ):
            merged[key] = value
    return merged


def smc_orb_fvg_candidate_grid() -> list[dict[str, Any]]:
    base = dict(SMC_ORB_FVG_BANK_DEFAULTS)
    candidates = [dict(SMC_ORB_FVG_BANK_LEGACY), dict(base)]
    tweaks = [
        {"smc_orb_require_fvg": False, "smc_orb_require_breakout": False},
        {"smc_orb_require_fvg": True, "smc_orb_require_breakout": True, "fvg_min_gap_pct": 0.004},
        {"smc_orb_range_min": 0.0, "smc_orb_range_max": 99999.0, "smc_orb_skip_wide_or": False},
        {"smc_orb_range_min": 120.0, "smc_orb_range_max": 200.0},
        {"smc_orb_stop_pts": 45.0, "smc_orb_target_pts": 110.0},
        {"smc_orb_stop_pts": 55.0, "smc_orb_target_pts": 130.0},
        {"smc_orb_rsi_call_min": 52, "smc_orb_rsi_call_max": 62, "smc_orb_rsi_put_min": 38, "smc_orb_rsi_put_max": 48},
        {"smc_orb_require_momentum": False, "smc_orb_require_breakout": True},
        {"orb_minutes": 12, "smc_orb_range_min": 100.0, "smc_orb_range_max": 220.0},
        {"orb_minutes": 18, "smc_orb_range_min": 100.0, "smc_orb_range_max": 220.0},
        {"entry_buffer_pct": 0.12, "fvg_min_gap_pct": 0.004, "smc_orb_require_breakout": True},
        {"smc_orb_entry_cutoff_min": 10 * 60 + 30, "smc_orb_stop_pts": 50.0, "smc_orb_target_pts": 115.0},
        {"smc_min_bars_between": 10, "smc_entry_scan_every": 3},
        {"smc_orb_require_fvg": False, "smc_orb_require_breakout": True, "smc_orb_stop_pts": 50.0, "smc_orb_target_pts": 120.0},
    ]
    for tweak in tweaks:
        row = deepcopy(base)
        row.update(tweak)
        candidates.append(row)
    return candidates


def score_smc_orb_fvg_backtest(result: dict[str, Any]) -> float:
    trades = int(result.get("total_trades") or 0)
    win_rate = float(result.get("win_rate") or 0)
    pf = float(result.get("profit_factor") or 0)
    pnl = float(result.get("total_pnl") or 0)
    if trades < 5:
        return win_rate * (trades / 5.0) - 10.0
    return (pnl / 2500.0) + min(pf, 3.0) * 22.0 + win_rate * 1.2 + min(trades, 25) * 0.15
