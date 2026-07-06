"""SMC FVG + OB + BOS (SCALP-SMC-004) parameter defaults for Bank Nifty."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from trading_shared.strategies.scalping_desk.smc_scalping_engine import DEFAULT_SMC_PARAMS

# Bank Nifty FVG+OB+BOS — tuned on 60d Angel One 1m sample.
SMC_FVG_OB_BOS_BANK_DEFAULTS: dict[str, Any] = {
    **DEFAULT_SMC_PARAMS,
    "volume_min": 0.0,
    "fvg_min_gap_pct": 0.006,
    "entry_buffer_pct": 0.08,
    "ob_impulse_atr": 0.85,
    "stop_atr_mult": 0.85,
    "target_atr_mult": 2.0,
    "trailing_atr_mult": 0.0,
    "bos_lookback_1m": 6,
    "bos_lookback_5m": 4,
    "max_hold_bars": 9,
    "fvg_stop_pts": 50.0,
    "fvg_target_pts": 120.0,
    "fvg_require_bos": True,
    "fvg_require_in_zone": True,
    "fvg_require_vwap_align": True,
    "fvg_allow_trend_fallback": False,
    "fvg_require_two_bar_momentum": True,
    "fvg_rsi_call_min": 53,
    "fvg_rsi_call_max": 60,
    "fvg_rsi_put_min": 40,
    "fvg_rsi_put_max": 46,
    "smc_entry_scan_every": 5,
    "smc_min_bars_between": 12,
    "smc_max_bars": 15000,
}

SMC_FVG_OB_BOS_BANK_LEGACY: dict[str, Any] = {
    **DEFAULT_SMC_PARAMS,
    "volume_min": 0.95,
    "fvg_require_bos": False,
    "fvg_require_in_zone": False,
    "fvg_require_vwap_align": False,
    "fvg_allow_trend_fallback": True,
    "fvg_require_two_bar_momentum": False,
}


def merge_smc_fvg_ob_bos_params(params: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(SMC_FVG_OB_BOS_BANK_DEFAULTS)
    if not params:
        return merged
    nested = params.get("smc_params")
    if isinstance(nested, dict):
        merged.update(nested)
    for key, value in params.items():
        if value is None:
            continue
        if key.startswith(("fvg_", "smc_", "stop_", "target_", "trailing_", "volume_", "bos_", "ob_", "entry_", "max_hold")):
            merged[key] = value
    return merged


def smc_fvg_candidate_grid() -> list[dict[str, Any]]:
    base = dict(SMC_FVG_OB_BOS_BANK_DEFAULTS)
    candidates = [dict(SMC_FVG_OB_BOS_BANK_LEGACY), dict(base)]
    tweaks = [
        {"fvg_stop_pts": 50.0, "fvg_target_pts": 100.0},
        {"fvg_stop_pts": 60.0, "fvg_target_pts": 120.0},
        {"fvg_rsi_call_min": 53, "fvg_rsi_call_max": 60, "fvg_rsi_put_min": 40, "fvg_rsi_put_max": 46},
        {"fvg_min_gap_pct": 0.005, "entry_buffer_pct": 0.07},
        {"fvg_min_gap_pct": 0.007, "entry_buffer_pct": 0.09},
        {"ob_impulse_atr": 0.75, "fvg_require_two_bar_momentum": True},
        {"ob_impulse_atr": 0.95, "fvg_require_bos": True},
        {"fvg_require_bos": True, "fvg_require_in_zone": True, "fvg_stop_pts": 55.0, "fvg_target_pts": 110.0},
        {"smc_min_bars_between": 15, "smc_entry_scan_every": 6},
        {"fvg_rsi_call_min": 53, "fvg_rsi_call_max": 60, "fvg_stop_pts": 55.0, "fvg_target_pts": 115.0},
        {"bos_lookback_1m": 5, "bos_lookback_5m": 3, "fvg_stop_pts": 52.0, "fvg_target_pts": 104.0},
        {"fvg_require_vwap_align": True, "fvg_require_in_zone": True, "fvg_allow_trend_fallback": False, "target_atr_mult": 2.2},
    ]
    for tweak in tweaks:
        row = deepcopy(base)
        row.update(tweak)
        candidates.append(row)
    return candidates


def score_smc_fvg_backtest(result: dict[str, Any]) -> float:
    trades = int(result.get("total_trades") or 0)
    win_rate = float(result.get("win_rate") or 0)
    pf = float(result.get("profit_factor") or 0)
    pnl = float(result.get("total_pnl") or 0)
    if trades < 6:
        return win_rate * (trades / 6.0) - 10.0
    return win_rate * 2.0 + min(pf, 2.5) * 12.0 + (pnl / 8000.0) + min(trades, 30) * 0.12
