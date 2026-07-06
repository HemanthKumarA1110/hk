"""Instrument and Redis key constants for scalping desk."""

from __future__ import annotations

INSTRUMENTS: dict[str, dict] = {
    "nifty50": {
        "underlying": "NIFTY",
        "label": "Nifty 50",
        "lot_size": 25,
        "exchange": "NSE",
        "option_exchange": "NFO",
        "points_step": 50,
    },
    "banknifty": {
        "underlying": "BANKNIFTY",
        "label": "Bank Nifty",
        "lot_size": 15,
        "exchange": "NSE",
        "option_exchange": "NFO",
        "points_step": 100,
    },
}

REDIS_DESK_PREFIX = "scalping:desk"
REDIS_CONFIG_SUFFIX = "config"
REDIS_STATE_SUFFIX = "state"
REDIS_VERSION_SUFFIX = "strategy_version"
REDIS_OPTIMIZATION_SUFFIX = "optimizations"

AI_CONFIDENCE_ENTER = 68
AI_CONFIDENCE_EXIT = 65
MIN_TRADE_GAP_MINUTES = 5
FORCE_EXIT_HOUR_IST = (15, 15)
DEFAULT_MAX_TRADES = 3

STRATEGY_VERSION = 8
STRATEGY_LABEL = "Battle-Tested Scalp"

# v3: quick target + tight stop + time exit — tuned on last month index data.
RISK_PROFILES: dict[str, dict[str, float | int]] = {
    "nifty50": {
        "target_atr_mult": 0.55,
        "stop_atr_mult": 1.2,
        "max_hold_bars": 10,
        "min_target_pts": 8,
    },
    "banknifty": {
        "target_atr_mult": 0.50,
        "stop_atr_mult": 1.2,
        "max_hold_bars": 8,
        "min_target_pts": 10,
    },
}

OPTION_DELTA_EST = 0.45
PREMIUM_SL_PCT = 0.12
PREMIUM_TGT_PCT = 0.08

# Desk only opens long options: BUY CE on CALL setups, BUY PE on PUT setups (no writing).
SCALP_EXECUTION_POLICY = "option_buy_only"


def option_contract_suffix(signal_type: str) -> str:
    return "CE" if str(signal_type or "").upper() == "CALL" else "PE"


def validate_option_buy_contract(symbol: str, signal_type: str) -> bool:
    sym = str(symbol or "").upper().strip()
    if not sym or sym.endswith("FUT") or "FUT" in sym:
        return False
    return sym.endswith(option_contract_suffix(signal_type))

INTERVAL_MAP = {"1m": "ONE_MINUTE", "3m": "THREE_MINUTE"}
