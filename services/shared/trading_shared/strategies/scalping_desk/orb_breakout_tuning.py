"""ORB breakout parameter defaults (SCALP-BT-002 Bank / SCALP-BT-004 Nifty)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# Nifty 50 ORB — retuned on ~60d Angel One 1m (2026-06-10→08-09).
# WR-primary: OR 45–80, ~4pt buffer, EMA8/20, RSI CALL 52–66 / PUT 32–46,
# vol 1.15, ATR momentum 0.25, prior-bar OFF, afternoon cutoff enabled.
ORB_BREAKOUT_NIFTY_DEFAULTS: dict[str, Any] = {
    "orb_minutes": 15,
    "orb_entry_cutoff_min": 14 * 60 + 45,
    # ~4 index points at Nifty ~24.1k.
    "orb_buffer_pct": 1.66e-4,
    "orb_vol_min": 1.15,
    "orb_use_vol_spike": False,
    "orb_rsi_call_min": 52,
    "orb_rsi_call_max": 66,
    "orb_rsi_put_min": 32,
    "orb_rsi_put_max": 46,
    "orb_require_inside_or": False,
    "orb_prior_mode": "off",
    "orb_require_two_bar_momentum": True,
    "orb_momentum_mode": "atr",
    "orb_momentum_atr_mult": 0.25,
    "orb_ema_fast": 8,
    "orb_ema_slow": 20,
    "orb_min_separation_pct": 0.0,
    "orb_vol_lookback": 0,
    "orb_require_rsi_slope": False,
    "orb_min_body_pct": 0.0,
    "orb_require_vwap": False,
    "orb_or_range_min": 45.0,
    "orb_or_range_max": 80.0,
    "orb_stop_pts": 6.0,
    "orb_target_pts": 12.0,
    "orb_max_hold_bars": 10,
    "orb_skip_wide_or": True,
}

# Pre-tune baseline (A/B): OR 40–80, ~2pt buffer, prior close-inside, morning cutoff.
ORB_BREAKOUT_NIFTY_LEGACY: dict[str, Any] = {
    "orb_minutes": 15,
    "orb_entry_cutoff_min": 10 * 60 + 30,
    "orb_buffer_pct": 8.0e-5,
    "orb_vol_min": 1.35,
    "orb_use_vol_spike": False,
    "orb_rsi_call_min": 50,
    "orb_rsi_call_max": 65,
    "orb_rsi_put_min": 34,
    "orb_rsi_put_max": 48,
    "orb_require_inside_or": True,
    "orb_prior_mode": "close_inside",
    "orb_require_two_bar_momentum": True,
    "orb_momentum_mode": "two_bar",
    "orb_momentum_atr_mult": 0.0,
    "orb_ema_fast": 9,
    "orb_ema_slow": 21,
    "orb_min_separation_pct": 0.0,
    "orb_vol_lookback": 0,
    "orb_require_rsi_slope": False,
    "orb_min_body_pct": 0.0,
    "orb_require_vwap": False,
    "orb_or_range_min": 40.0,
    "orb_or_range_max": 80.0,
    "orb_stop_pts": 6.0,
    "orb_target_pts": 12.0,
    "orb_max_hold_bars": 10,
    "orb_skip_wide_or": True,
}

# Bank Nifty ORB — retuned 60d Angel One 1m: buffer ~3pts + CALL RSI 50–65 → ~80% WR.
ORB_BREAKOUT_BANK_DEFAULTS: dict[str, Any] = {
    "orb_minutes": 15,
    "orb_entry_cutoff_min": 10 * 60 + 30,
    # ~3 index points at Bank Nifty ~57.7k (was 0.0003 ≈ 17pts).
    "orb_buffer_pct": 5.2e-5,
    "orb_vol_min": 1.35,
    "orb_use_vol_spike": False,
    "orb_rsi_call_min": 50,
    "orb_rsi_call_max": 65,
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


def orb_breakout_defaults(instrument_key: str) -> dict[str, Any]:
    if instrument_key == "nifty50":
        return dict(ORB_BREAKOUT_NIFTY_DEFAULTS)
    return dict(ORB_BREAKOUT_BANK_DEFAULTS)


def merge_orb_params(
    params: dict[str, Any] | None = None,
    instrument_key: str = "banknifty",
) -> dict[str, Any]:
    """Merge desk params with instrument ORB defaults."""
    merged = orb_breakout_defaults(instrument_key)
    if not params:
        return merged
    nested = params.get("orb_breakout")
    if isinstance(nested, dict):
        merged.update(nested)
    for key, value in params.items():
        if key.startswith("orb_") and value is not None:
            merged[key] = value
    return merged


def orb_candidate_grid(instrument_key: str = "banknifty") -> list[dict[str, Any]]:
    """Small candidate set for fast win-rate tuning."""
    if instrument_key == "nifty50":
        base = dict(ORB_BREAKOUT_NIFTY_DEFAULTS)
        candidates = [dict(ORB_BREAKOUT_NIFTY_LEGACY), dict(base)]
        tweaks = [
            {"orb_or_range_min": 35.0, "orb_or_range_max": 90.0, "orb_skip_wide_or": True},
            {"orb_stop_pts": 7.0, "orb_target_pts": 14.0},
            {"orb_buffer_pct": 0.00012, "orb_vol_min": 1.25},
            {"orb_require_two_bar_momentum": False},
            {"orb_minutes": 12},
            {"orb_minutes": 18},
        ]
    else:
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
