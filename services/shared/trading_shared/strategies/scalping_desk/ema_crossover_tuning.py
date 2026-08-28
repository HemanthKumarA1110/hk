"""EMA crossover + RSI parameter defaults (SCALP-BT-003 Bank; Nifty legacy helpers retained)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# Nifty 50 EMA+RSI — same profit philosophy as Bank BT-003, Nifty point scale.
# VWAP off + tighter PUT RSI + slightly wider stop vs legacy 6/12.
EMA_CROSSOVER_NIFTY_DEFAULTS: dict[str, Any] = {
    "ema_fast": 8,
    "ema_slow": 21,
    "ema_cross_lookback": 3,
    "ema_rsi_call_min": 53,
    "ema_rsi_call_max": 60,
    "ema_rsi_put_min": 38,
    "ema_rsi_put_max": 46,
    "ema_require_vwap": False,
    "ema_require_two_bar_momentum": True,
    "ema_vol_min": 0.0,
    "ema_use_vol_spike": False,
    "ema_min_separation_pct": 0.0,
    "ema_stop_pts": 7.0,
    "ema_target_pts": 14.0,
    "ema_max_hold_bars": 10,
}

EMA_CROSSOVER_NIFTY_LEGACY: dict[str, Any] = {
    "ema_fast": 9,
    "ema_slow": 21,
    "ema_cross_lookback": 3,
    "ema_rsi_call_min": 50,
    "ema_rsi_call_max": 65,
    "ema_rsi_put_min": 35,
    "ema_rsi_put_max": 50,
    "ema_require_vwap": True,
    "ema_require_two_bar_momentum": True,
    "ema_vol_min": 0.0,
    "ema_use_vol_spike": False,
    "ema_min_separation_pct": 0.0,
    "ema_stop_pts": 6.0,
    "ema_target_pts": 12.0,
    "ema_max_hold_bars": 10,
}

# Bank Nifty EMA+RSI — profit retune (Angel 1m ~60d): VWAP off + PUT 38–46 + stop 75
# → ~61% WR, ~2.5× PnL vs VWAP-on 65/130 (more fills, wider stop).
EMA_CROSSOVER_BANK_DEFAULTS: dict[str, Any] = {
    "ema_fast": 8,
    "ema_slow": 21,
    "ema_cross_lookback": 3,
    "ema_rsi_call_min": 53,
    "ema_rsi_call_max": 60,
    "ema_rsi_put_min": 38,
    "ema_rsi_put_max": 46,
    "ema_require_vwap": False,
    "ema_require_two_bar_momentum": True,
    "ema_vol_min": 0.0,
    "ema_use_vol_spike": False,
    "ema_min_separation_pct": 0.0,
    "ema_stop_pts": 75.0,
    "ema_target_pts": 150.0,
    "ema_max_hold_bars": 8,
}

EMA_CROSSOVER_BANK_LEGACY: dict[str, Any] = {
    "ema_fast": 9,
    "ema_slow": 21,
    "ema_cross_lookback": 3,
    "ema_rsi_call_min": 50,
    "ema_rsi_call_max": 65,
    "ema_rsi_put_min": 35,
    "ema_rsi_put_max": 50,
    "ema_require_vwap": True,
    "ema_require_two_bar_momentum": True,
    "ema_vol_min": 0.0,
    "ema_use_vol_spike": False,
    "ema_min_separation_pct": 0.0,
    "ema_stop_pts": 65.0,
    "ema_target_pts": 130.0,
    "ema_max_hold_bars": 8,
}


def ema_crossover_defaults(instrument_key: str) -> dict[str, Any]:
    if instrument_key == "banknifty":
        return dict(EMA_CROSSOVER_BANK_DEFAULTS)
    return dict(EMA_CROSSOVER_NIFTY_DEFAULTS)


def merge_ema_crossover_params(
    params: dict[str, Any] | None = None,
    instrument_key: str = "banknifty",
) -> dict[str, Any]:
    merged = ema_crossover_defaults(instrument_key)
    if not params:
        return merged
    nested = params.get("ema_crossover")
    if isinstance(nested, dict):
        merged.update(nested)
    for key, value in params.items():
        if key.startswith("ema_") and value is not None:
            merged[key] = value
    return merged


def ema_candidate_grid(instrument_key: str = "banknifty") -> list[dict[str, Any]]:
    if instrument_key == "nifty50":
        base = dict(EMA_CROSSOVER_NIFTY_DEFAULTS)
        candidates = [dict(EMA_CROSSOVER_NIFTY_LEGACY), dict(base)]
        tweaks = [
            {"ema_require_vwap": True, "ema_stop_pts": 6.0, "ema_target_pts": 12.0},
            {"ema_stop_pts": 8.0, "ema_target_pts": 16.0},
            {"ema_require_two_bar_momentum": False},
            {"ema_cross_lookback": 2},
            {"ema_cross_lookback": 4},
        ]
    else:
        base = dict(EMA_CROSSOVER_BANK_DEFAULTS)
        candidates = [dict(EMA_CROSSOVER_BANK_LEGACY), dict(base)]
        tweaks = [
            {"ema_rsi_call_min": 52, "ema_rsi_call_max": 62, "ema_rsi_put_min": 38, "ema_rsi_put_max": 48},
            {"ema_rsi_call_min": 53, "ema_rsi_call_max": 60, "ema_rsi_put_min": 35, "ema_rsi_put_max": 45},
            {"ema_require_vwap": True, "ema_stop_pts": 65.0, "ema_target_pts": 130.0},
            {"ema_stop_pts": 65.0, "ema_target_pts": 130.0},
            {"ema_require_two_bar_momentum": False},
            {"ema_cross_lookback": 2},
            {"ema_cross_lookback": 4},
            {"ema_require_vwap": True},
            {"ema_stop_pts": 75.0, "ema_target_pts": 150.0, "ema_rsi_put_min": 35, "ema_rsi_put_max": 45},
        ]
    for tweak in tweaks:
        row = deepcopy(base)
        row.update(tweak)
        candidates.append(row)
    return candidates


def score_ema_backtest(result: dict[str, Any]) -> float:
    trades = int(result.get("total_trades") or 0)
    win_rate = float(result.get("win_rate") or 0)
    pf = float(result.get("profit_factor") or 0)
    pnl = float(result.get("total_pnl") or 0)
    if trades < 8:
        return win_rate * (trades / 8.0) - 10.0
    return win_rate * 2.0 + min(pf, 2.5) * 12.0 + (pnl / 8000.0) + min(trades, 40) * 0.12
