"""SMC ORB + FVG (SCALP-SMC-006) parameter defaults for Bank Nifty."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from trading_shared.strategies.scalping_desk.smc_scalping_engine import DEFAULT_SMC_PARAMS

# Bank Nifty SMC ORB+FVG — tuned on 60d Angel One 1m (looser entries + fixed R:R).
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
    "smc_orb_entry_cutoff_min": 10 * 60 + 45,
    "smc_orb_require_fvg": False,
    "smc_orb_require_breakout": True,
    "smc_orb_require_momentum": True,
    "smc_orb_stop_pts": 50.0,
    "smc_orb_target_pts": 120.0,
    "smc_orb_rsi_call_min": 50,
    "smc_orb_rsi_call_max": 66,
    "smc_orb_rsi_put_min": 34,
    "smc_orb_rsi_put_max": 50,
    "smc_entry_scan_every": 3,
    "smc_min_bars_between": 8,
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


def merge_smc_orb_fvg_params(params: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(SMC_ORB_FVG_BANK_DEFAULTS)
    if not params:
        return merged
    nested = params.get("smc_params") if isinstance(params.get("smc_params"), dict) else {}
    for source in (nested, params):
        for key, value in source.items():
            if key in merged or key.startswith(("smc_orb_", "smc_entry", "smc_min", "smc_max")):
                continue
            if value is not None:
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
