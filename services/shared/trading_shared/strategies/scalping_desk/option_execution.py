"""Option leg resolution for scalping desk — buy-only vs buy+sell (short leg)."""

from __future__ import annotations

from typing import Any

from trading_shared.strategies.scalping_desk.constants import (
    SCALP_EXECUTION_POLICY,
    validate_option_buy_contract,
)
from trading_shared.strategies.scalping_desk.engine import should_exit

OPTION_EXECUTION_BUY_ONLY = "buy_only"
OPTION_EXECUTION_BUY_AND_SELL = "buy_and_sell"

# Approximate Angel index-option sell margin for backtest lot caps (not full SPAN).
SELL_OPTION_MARGIN_PCT = 0.15


def resolve_option_trade(signal_type: str, execution_mode: str) -> tuple[str, str]:
    """
    Map setup direction to order side and pick_strike signal type.

    buy_only:      CALL → BUY CE,  PUT → BUY PE
    buy_and_sell:  CALL → SELL PE, PUT → SELL CE  (short opposite leg)
    """
    st = str(signal_type or "").upper()
    mode = execution_mode or OPTION_EXECUTION_BUY_ONLY
    if mode == OPTION_EXECUTION_BUY_AND_SELL:
        if st == "CALL":
            return "SELL", "PUT"
        return "SELL", "CALL"
    return "BUY", st


def adapt_signal_for_execution(
    signal: dict[str, Any],
    execution_mode: str = OPTION_EXECUTION_BUY_ONLY,
) -> dict[str, Any]:
    """Adjust premium target/stop for long vs short option leg."""
    side, pick_type = resolve_option_trade(str(signal.get("signal_type") or ""), execution_mode)
    entry = float(signal.get("entry") or 0)
    target = float(signal.get("target") or entry)
    stoploss = float(signal.get("stoploss") or entry)
    sl_width = abs(entry - stoploss) or max(entry * 0.12, 3.0)
    tgt_width = abs(target - entry) or max(entry * 0.08, 2.0)

    if side == "SELL":
        stoploss = round(entry + sl_width, 2)
        target = round(max(0.05, entry - tgt_width), 2)

    suffix = "CE" if pick_type == "CALL" else "PE"
    symbol = str(signal.get("option_symbol") or "")
    if side == "BUY" and symbol and not validate_option_buy_contract(symbol, pick_type):
        symbol = ""

    return {
        **signal,
        "order_side": side,
        "option_pick_type": pick_type,
        "option_leg": suffix,
        "execution_mode": execution_mode,
        "entry": round(entry, 2),
        "target": target,
        "stoploss": stoploss,
        "option_symbol": symbol,
    }


def should_exit_option_position(
    *,
    order_side: str,
    signal_type: str,
    current_ltp: float,
    entry: float,
    target: float,
    stoploss: float,
    indicators: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    side = str(order_side or "BUY").upper()
    if side == "SELL":
        if current_ltp <= target:
            return True, "target_hit"
        if current_ltp >= stoploss:
            return True, "stoploss_hit"
        return False, ""
    return should_exit(
        signal_type,
        current_ltp,
        entry,
        target,
        stoploss,
        indicators or {},
    )


def option_trade_pnl(
    entry_premium: float,
    exit_premium: float,
    lot_size: int,
    lots: int,
    *,
    order_side: str = "BUY",
) -> float:
    mult = lot_size * max(lots, 1)
    if str(order_side).upper() == "SELL":
        return (float(entry_premium) - float(exit_premium)) * mult
    return (float(exit_premium) - float(entry_premium)) * mult


def backtest_sell_margin_lots(
    deployable: float,
    spot: float,
    lot_size: int,
    *,
    margin_pct: float = SELL_OPTION_MARGIN_PCT,
) -> int:
    per_lot = spot * lot_size * margin_pct
    if per_lot <= 0 or deployable <= 0:
        return 0
    return int(deployable // per_lot)


def execution_mode_label(mode: str) -> str:
    if mode == OPTION_EXECUTION_BUY_AND_SELL:
        return "CE/PE Buy and Sell"
    return "CE/PE Buy only"


def ensure_buy_only_signal(signal: dict[str, Any]) -> dict[str, Any]:
    """Live desk policy: long CE on CALL, long PE on PUT — never write options on entry."""
    out = adapt_signal_for_execution(signal, OPTION_EXECUTION_BUY_ONLY)
    out["order_side"] = "BUY"
    out["execution_policy"] = OPTION_EXECUTION_BUY_ONLY
    symbol = str(out.get("option_symbol") or "")
    if symbol and not validate_option_buy_contract(symbol, str(out.get("signal_type") or "")):
        out["option_symbol"] = ""
        out["option_token"] = ""
    return out
