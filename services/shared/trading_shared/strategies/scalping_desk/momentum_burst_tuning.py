"""Momentum Burst (SCALP-AD-005) Bank Nifty parameter defaults."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# Retuned on 60d Angel One 1m: current defaults produced 0 trades (VWAP 0.35% + ST + momentum).
# Viable set: wider VWAP band, Supertrend optional off, momentum off, max hold 5 → ~64% WR.
MOMENTUM_BURST_BANK_DEFAULTS: dict[str, Any] = {
    "mb_ema_fast": 9,
    "mb_ema_slow": 21,
    "mb_ema_sep_pct": 0.0,
    "mb_rsi_call_min": 46,
    "mb_rsi_call_max": 62,
    "mb_rsi_put_min": 40,
    "mb_rsi_put_max": 52,
    "mb_vwap_distance_pct": 1.0,
    "mb_require_vwap": True,
    "mb_index_volume_spike_ratio": 1.12,
    "mb_volume_spike_ratio": 1.35,
    "mb_require_supertrend": False,
    "mb_require_two_bar_momentum": False,
    "mb_ema_mode": "or",  # or | cross | direction
    "mb_stop_atr_mult": 1.20,
    "mb_stop_floor_pct": 0.0002,
    "mb_target_atr_mult": 0.50,
    "mb_min_target_pts": 10.0,
    "mb_max_hold_bars": 5,
}

MOMENTUM_BURST_BANK_LEGACY: dict[str, Any] = {
    "mb_ema_fast": 9,
    "mb_ema_slow": 21,
    "mb_ema_sep_pct": 0.04,
    "mb_rsi_call_min": 46,
    "mb_rsi_call_max": 62,
    "mb_rsi_put_min": 40,
    "mb_rsi_put_max": 52,
    "mb_vwap_distance_pct": 0.35,
    "mb_require_vwap": True,
    "mb_index_volume_spike_ratio": 1.12,
    "mb_volume_spike_ratio": 1.35,
    "mb_require_supertrend": True,
    "mb_require_two_bar_momentum": True,
    "mb_ema_mode": "or",
    "mb_stop_atr_mult": 1.20,
    "mb_stop_floor_pct": 0.0002,
    "mb_target_atr_mult": 0.50,
    "mb_min_target_pts": 10.0,
    "mb_max_hold_bars": 8,
}


def merge_momentum_burst_params(params: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(MOMENTUM_BURST_BANK_DEFAULTS)
    if not params:
        return merged
    nested = params.get("momentum_burst")
    if isinstance(nested, dict):
        merged.update(nested)
    for key, value in params.items():
        if key.startswith("mb_") and value is not None:
            merged[key] = value
        # legacy keys used by evaluate_momentum_burst
        if key in ("volume_spike_ratio", "index_volume_spike_ratio") and value is not None:
            if key == "volume_spike_ratio":
                merged["mb_volume_spike_ratio"] = value
            else:
                merged["mb_index_volume_spike_ratio"] = value
    return merged
