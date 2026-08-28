"""INTRA-ORB (OpeningRangeBreakout) tunable defaults for equity cash."""

from __future__ import annotations

from datetime import time
from typing import Any

# Nifty 50 equity cash ORB — OFAT on DB 5m (2026-06→08), active breakout names.
# Latest pass favored a narrower, more selective breakout profile with a shorter
# entry window and slower EMA filter, which improved average winner without
# introducing trailing logic. Sample is still thin, so forward paper carefully.
INTRA_ORB_DEFAULTS: dict[str, Any] = {
    "or_start_min": 9 * 60 + 15,  # 09:15
    "or_end_min": 9 * 60 + 55,  # 09:55
    "entry_start_min": 9 * 60 + 55,
    "entry_end_min": 10 * 60 + 30,
    "force_exit_min": 15 * 60,  # 15:00
    "min_or_width_pct": 0.20,
    "max_or_width_pct": 1.20,
    "breakout_buffer_pct": 0.15,
    "vol_mult": 1.0,
    "vol_lookback": 10,
    "require_vol_rising": False,
    "ema_period": 34,
    "ema_slope": False,
    "ema_min_dist_pct": 0.0,
    "first_breakout_mode": "prev_close_inside",
    "candle_body_min": 0.60,
    "require_high_break": False,
    "stop_method": "pct",
    "stop_pct": 0.20,
    "stop_atr_mult": 1.0,
    "max_risk_pct": 0.40,
    "min_rr": 3.0,
    "trail_after_r": 0.0,
    "trail_atr_mult": 0.0,
    "retest_mode": "off",
}

INTRA_ORB_LEGACY: dict[str, Any] = {
    "or_start_min": 9 * 60 + 15,
    "or_end_min": 9 * 60 + 45,
    "entry_start_min": 9 * 60 + 45,
    "entry_end_min": 11 * 60 + 30,
    "force_exit_min": 15 * 60 + 15,
    "min_or_width_pct": 0.25,
    "max_or_width_pct": 1.60,
    "breakout_buffer_pct": 0.08,
    "vol_mult": 1.5,
    "vol_lookback": 20,
    "require_vol_rising": False,
    "ema_period": 21,
    "ema_slope": False,
    "ema_min_dist_pct": 0.0,
    "first_breakout_mode": "prev_close_inside",
    "candle_body_min": 0.0,
    "require_high_break": False,
    "stop_method": "or_mid",
    "stop_pct": 0.40,
    "stop_atr_mult": 1.0,
    "max_risk_pct": 0.80,
    "min_rr": 2.0,
    "trail_after_r": 0.0,
    "trail_atr_mult": 0.0,
    "retest_mode": "off",
}


def merge_intra_orb_params(params: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(INTRA_ORB_DEFAULTS)
    if not params:
        return merged
    nested = params.get("intra_orb") if isinstance(params.get("intra_orb"), dict) else {}
    if nested:
        merged.update({k: v for k, v in nested.items() if v is not None})
    for key, value in params.items():
        if value is None or key == "intra_orb":
            continue
        if key in merged or key.startswith(("or_", "entry_", "force_", "min_", "max_", "breakout_", "vol_", "ema_", "first_", "candle_", "stop_", "trail_", "retest_", "require_")):
            merged[key] = value
    return merged


def minutes_to_time(minutes: int) -> time:
    minutes = int(minutes)
    return time(minutes // 60, minutes % 60)
