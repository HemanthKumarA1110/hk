"""INTRA-VWAP-ORB (VwapOrbTrendFilter) tunable defaults for equity cash."""

from __future__ import annotations

from datetime import time
from typing import Any

# OFAT + walk-forward on Angel One 5m (2026-02-14→2026-08-13, 8 Nifty names).
# Best combo vs prompt baseline: WR 31.5%→53.1% and ~45% smaller loss after costs.
# Still net-negative (PF 0.47) — do not treat as a live edge.
INTRA_VWAP_ORB_DEFAULTS: dict[str, Any] = {
    "ema_fast": 5,
    "ema_slow": 13,
    "atr_period": 14,
    "vol_lookback": 8,
    "vol_mult": 1.35,
    "atr_stop_mult": 1.5,
    "breakeven_atr_mult": 1.5,
    "scale_out_r": 1.0,
    "risk_pct": 1.0,
    "max_trades_per_day": 1,
    "max_consec_stops": 1,
    "or_end_min": 9 * 60 + 30,  # 09:30
    "entry_start_min": 9 * 60 + 30,
    "entry_end_min": 14 * 60,  # 14:00
    "force_exit_min": 15 * 60 + 15,
    "long_only": False,
}

INTRA_VWAP_ORB_LEGACY: dict[str, Any] = {
    "ema_fast": 9,
    "ema_slow": 21,
    "atr_period": 14,
    "vol_lookback": 10,
    "vol_mult": 1.5,
    "atr_stop_mult": 1.5,
    "breakeven_atr_mult": 1.0,
    "scale_out_r": 1.5,
    "risk_pct": 1.0,
    "max_trades_per_day": 2,
    "max_consec_stops": 2,
    "or_end_min": 9 * 60 + 30,
    "entry_start_min": 9 * 60 + 20,
    "entry_end_min": 14 * 60 + 45,
    "force_exit_min": 15 * 60 + 15,
    "long_only": False,
}


def minutes_to_time(total_minutes: int) -> time:
    total_minutes = int(total_minutes) % (24 * 60)
    return time(total_minutes // 60, total_minutes % 60)


def merge_intra_vwap_orb_params(params: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(INTRA_VWAP_ORB_DEFAULTS)
    if not params:
        return merged
    nested = params.get("intra_vwap_orb") if isinstance(params.get("intra_vwap_orb"), dict) else {}
    if nested:
        merged.update({k: v for k, v in nested.items() if v is not None})
    for key, value in params.items():
        if value is None or key == "intra_vwap_orb":
            continue
        if key in merged or key.startswith(
            ("ema_", "atr_", "vol_", "breakeven_", "scale_", "risk_", "max_", "or_", "entry_", "force_", "long_")
        ):
            merged[key] = value
    return merged
