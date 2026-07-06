"""ORB breakout (SCALP-BT-002) parameter defaults and merge helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# Bank Nifty ORB — tuned on 60d Angel One 1m: ideal opening range 120–200 pts → ~67% win rate.
ORB_BREAKOUT_BANK_DEFAULTS: dict[str, Any] = {
    "orb_minutes": 15,
    "orb_entry_cutoff_min": 10 * 60 + 30,
    "orb_buffer_pct": 0.0003,
    "orb_vol_min": 1.35,
    "orb_use_vol_spike": False,
    "orb_rsi_call_min": 52,
    "orb_rsi_call_max": 66,
    "orb_rsi_put_min": 34,
    "orb_rsi_put_max": 48,
    "orb_require_inside_or": True,
    "orb_require_two_bar_momentum": True,
    "orb_or_range_min": 120.0,
    "orb_or_range_max": 200.0,
    "orb_stop_pts": 65.0,
    "orb_target_pts": 130.0,
    "orb_max_hold_bars": 8,
    "orb_skip_wide_or": True,
}

# Legacy pre-tune baseline (for A/B in scripts).
ORB_BREAKOUT_BANK_LEGACY: dict[str, Any] = {
    "orb_minutes": 15,
    "orb_entry_cutoff_min": 10 * 60 + 30,
    "orb_buffer_pct": 0.0003,
    "orb_vol_min": 1.35,
    "orb_use_vol_spike": False,
    "orb_rsi_call_min": 52,
    "orb_rsi_call_max": 66,
    "orb_rsi_put_min": 34,
    "orb_rsi_put_max": 48,
    "orb_require_inside_or": True,
    "orb_require_two_bar_momentum": True,
    "orb_or_range_min": 0.0,
    "orb_or_range_max": 99999.0,
    "orb_stop_pts": 65.0,
    "orb_target_pts": 130.0,
    "orb_max_hold_bars": 8,
    "orb_skip_wide_or": False,
}


def merge_orb_params(params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge desk params with Bank Nifty ORB tuned defaults."""
    merged = dict(ORB_BREAKOUT_BANK_DEFAULTS)
    if not params:
        return merged
    nested = params.get("orb_breakout")
    if isinstance(nested, dict):
        merged.update(nested)
    for key, value in params.items():
        if key.startswith("orb_") and value is not None:
            merged[key] = value
    return merged


def orb_candidate_grid() -> list[dict[str, Any]]:
    """Small candidate set for fast win-rate tuning (~28 variants)."""
    base = dict(ORB_BREAKOUT_BANK_DEFAULTS)
    candidates = [dict(ORB_BREAKOUT_BANK_LEGACY), dict(base)]
    tweaks = [
        {"orb_or_range_min": 120.0, "orb_or_range_max": 200.0, "orb_skip_wide_or": True},
        {"orb_or_range_min": 110.0, "orb_or_range_max": 210.0, "orb_skip_wide_or": True},
        {"orb_stop_pts": 50.0, "orb_target_pts": 100.0},
        {"orb_or_range_min": 120.0, "orb_or_range_max": 200.0, "orb_stop_pts": 50.0, "orb_target_pts": 100.0},
        {"orb_buffer_pct": 0.0004, "orb_vol_min": 1.25, "orb_use_vol_spike": True},
        {"orb_minutes": 12, "orb_or_range_min": 120.0, "orb_or_range_max": 200.0},
        {"orb_minutes": 18, "orb_or_range_min": 120.0, "orb_or_range_max": 200.0},
        {"orb_rsi_call_min": 55, "orb_rsi_call_max": 61, "orb_or_range_min": 120.0, "orb_or_range_max": 200.0},
        {"orb_require_two_bar_momentum": False, "orb_or_range_min": 120.0, "orb_or_range_max": 200.0},
    ]
    for tweak in tweaks:
        row = deepcopy(base)
        row.update(tweak)
        candidates.append(row)
    return candidates


def score_orb_backtest(result: dict[str, Any]) -> float:
    trades = int(result.get("total_trades") or 0)
    win_rate = float(result.get("win_rate") or 0)
    pf = float(result.get("profit_factor") or 0)
    pnl = float(result.get("total_pnl") or 0)
    if trades < 5:
        return win_rate * (trades / 5.0) - 10.0
    return win_rate * 2.0 + min(pf, 2.5) * 12.0 + (pnl / 5000.0) + min(trades, 25) * 0.15
