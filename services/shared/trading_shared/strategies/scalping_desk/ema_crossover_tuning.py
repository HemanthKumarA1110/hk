"""EMA crossover + RSI (SCALP-BT-003) parameter defaults for Bank Nifty."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# Bank Nifty EMA+RSI — tuned on 60d Angel One 1m: tighter RSI bands → ~68% win rate.
EMA_CROSSOVER_BANK_DEFAULTS: dict[str, Any] = {
    "ema_cross_lookback": 3,
    "ema_rsi_call_min": 53,
    "ema_rsi_call_max": 60,
    "ema_rsi_put_min": 40,
    "ema_rsi_put_max": 46,
    "ema_require_vwap": True,
    "ema_require_two_bar_momentum": True,
    "ema_vol_min": 0.0,
    "ema_use_vol_spike": False,
    "ema_min_separation_pct": 0.0,
    "ema_stop_pts": 65.0,
    "ema_target_pts": 130.0,
    "ema_max_hold_bars": 8,
}

EMA_CROSSOVER_BANK_LEGACY: dict[str, Any] = {
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


def merge_ema_crossover_params(params: dict[str, Any] | None = None) -> dict[str, Any]:
    merged = dict(EMA_CROSSOVER_BANK_DEFAULTS)
    if not params:
        return merged
    nested = params.get("ema_crossover")
    if isinstance(nested, dict):
        merged.update(nested)
    for key, value in params.items():
        if key.startswith("ema_") and value is not None:
            merged[key] = value
    return merged


def ema_candidate_grid() -> list[dict[str, Any]]:
    base = dict(EMA_CROSSOVER_BANK_DEFAULTS)
    candidates = [dict(EMA_CROSSOVER_BANK_LEGACY), dict(base)]
    tweaks = [
        {"ema_rsi_call_min": 52, "ema_rsi_call_max": 62, "ema_rsi_put_min": 38, "ema_rsi_put_max": 48},
        {"ema_rsi_call_min": 53, "ema_rsi_call_max": 60, "ema_rsi_put_min": 40, "ema_rsi_put_max": 46},
        {"ema_stop_pts": 55.0, "ema_target_pts": 110.0},
        {"ema_rsi_call_min": 52, "ema_rsi_call_max": 62, "ema_stop_pts": 55.0, "ema_target_pts": 110.0},
        {"ema_require_two_bar_momentum": False},
        {"ema_cross_lookback": 2},
        {"ema_cross_lookback": 4},
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
