"""VWAP Bounce parameter defaults (SCALP-AD-002 Nifty / SCALP-AD-006 Bank)."""

from __future__ import annotations

from typing import Any

# Nifty 50 — retuned on ~60d Angel One 1m (2026-06-10→08-09).
# Baseline hardcoded filters fired 0 battle-window trades on this sample.
# WR-primary viable set: 0.20% VWAP band, deeper CALL prev RSI, color+close-loc,
# tighter stop (~0.70× profile), smaller target (~0.20× profile mult), hold 12.
# Pre-tune equivalent defaults kept in comments / LEGACY path via prior commit history.
VWAP_BOUNCE_NIFTY_DEFAULTS: dict[str, Any] = {
    "vb_near_atr_mult": 0.0,
    "vb_near_pct": 0.20,
    "vb_call_prev_rsi_max": 42,
    "vb_call_rsi_min": 45,
    "vb_call_rsi_max": 58,
    "vb_put_prev_rsi_min": 54,
    "vb_put_rsi_min": 42,
    "vb_put_rsi_max": 55,
    "vb_rsi_turn_min": 0.0,
    "vb_candle_mode": "color",
    "vb_multi_bar": 1,
    "vb_side_mode": "touch",
    "vb_side_displace_atr": 0.0,
    "vb_close_loc_pct": 0.60,
    "vb_stop_atr_mult": 0.84,  # ≈ stop_mult 0.70 × profile 1.2
    "vb_stop_floor_pct": 0.0002,
    "vb_target_atr_mult": 0.11,  # ≈ target_mult 0.20 × profile 0.55
    "vb_min_target_pts": 8.0,
    "vb_max_hold_bars": 12,
}

# Exact pre-tune hardcoded behavior (A/B / rollback).
VWAP_BOUNCE_NIFTY_LEGACY: dict[str, Any] = {
    "vb_near_atr_mult": 0.25,
    "vb_near_pct": 0.0,
    "vb_call_prev_rsi_max": 45,
    "vb_call_rsi_min": 45,
    "vb_call_rsi_max": 58,
    "vb_put_prev_rsi_min": 55,
    "vb_put_rsi_min": 42,
    "vb_put_rsi_max": 55,
    "vb_rsi_turn_min": 0.0,
    "vb_candle_mode": "color",
    "vb_multi_bar": 1,
    "vb_side_mode": "touch",
    "vb_side_displace_atr": 0.0,
    "vb_close_loc_pct": 0.0,
    "vb_stop_atr_mult": 1.14,
    "vb_stop_floor_pct": 0.0002,
    "vb_target_atr_mult": 0.2475,
    "vb_min_target_pts": 8.0,
    "vb_max_hold_bars": 8,
}

# Retuned on ~60d Angel One 1m Bank Nifty (2026-06-10→2026-08-09).
VWAP_BOUNCE_BANK_DEFAULTS: dict[str, Any] = {
    "vb_near_atr_mult": 0.0,
    "vb_near_pct": 0.25,
    "vb_call_prev_rsi_max": 43,
    "vb_call_rsi_min": 43,
    "vb_call_rsi_max": 55,
    "vb_put_prev_rsi_min": 54,
    "vb_put_rsi_min": 44,
    "vb_put_rsi_max": 58,
    "vb_rsi_turn_min": 0.0,
    "vb_candle_mode": "off",
    "vb_multi_bar": 1,
    "vb_side_mode": "touch",
    "vb_side_displace_atr": 0.05,
    "vb_close_loc_pct": 0.0,
    "vb_stop_atr_mult": 1.14,
    "vb_stop_floor_pct": 0.0002,
    "vb_target_atr_mult": 0.225,
    "vb_min_target_pts": 10.0,
    "vb_max_hold_bars": 6,
}

VWAP_BOUNCE_BANK_LEGACY: dict[str, Any] = {
    "vb_near_atr_mult": 0.25,
    "vb_near_pct": 0.0,
    "vb_call_prev_rsi_max": 45,
    "vb_call_rsi_min": 45,
    "vb_call_rsi_max": 58,
    "vb_put_prev_rsi_min": 55,
    "vb_put_rsi_min": 42,
    "vb_put_rsi_max": 55,
    "vb_rsi_turn_min": 0.0,
    "vb_candle_mode": "color",
    "vb_multi_bar": 1,
    "vb_side_mode": "touch",
    "vb_side_displace_atr": 0.05,
    "vb_close_loc_pct": 0.0,
    "vb_stop_atr_mult": 1.14,
    "vb_stop_floor_pct": 0.0002,
    "vb_target_atr_mult": 0.225,
    "vb_min_target_pts": 10.0,
    "vb_max_hold_bars": 6,
}


def vwap_bounce_defaults(instrument_key: str = "banknifty") -> dict[str, Any]:
    if instrument_key == "nifty50":
        return dict(VWAP_BOUNCE_NIFTY_DEFAULTS)
    return dict(VWAP_BOUNCE_BANK_DEFAULTS)


def merge_vwap_bounce_params(
    params: dict[str, Any] | None = None,
    instrument_key: str = "banknifty",
) -> dict[str, Any]:
    merged = vwap_bounce_defaults(instrument_key)
    if not params:
        return merged
    nested = params.get("vwap_bounce")
    if isinstance(nested, dict):
        merged.update(nested)
    for key, value in params.items():
        if key.startswith("vb_") and value is not None:
            merged[key] = value
    return merged
