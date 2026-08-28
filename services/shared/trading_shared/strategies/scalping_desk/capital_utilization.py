"""
Full-capital utilization sizing for Nifty / Bank Nifty index scalping.

Rules:
- One open trade at a time (enforced in guards + sizer).
- Deploy up to capital_utilization_pct of deployable margin per trade.
- Session capital is fixed at IST day open; intraday profits do not increase
  deployable size (Angel One T+1 credit). Intraday losses reduce deployable margin.
"""

from __future__ import annotations

import re
from typing import Any

from trading_shared.execution.qty import max_lots_per_order

# Leave headroom for brokerage, taxes, and a 1-tick premium move on split fills.
CASH_BUFFER_PCT = 0.03
_INSUFFICIENT_FUNDS_RE = re.compile(
    r"Available funds\s*-\s*(?:Rs\.?|₹)?\s*([0-9,]+\.?[0-9]*).*?require(?:s)?\s*(?:Rs\.?|₹)?\s*([0-9,]+\.?[0-9]*)",
    re.IGNORECASE | re.DOTALL,
)
from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS
from trading_shared.strategies.scalping_desk.daily_stop import trading_day_key

INDEX_SCALP_KEYS = frozenset({"nifty50", "banknifty"})


def is_index_scalp_desk(instrument_key: str) -> bool:
    return instrument_key in INDEX_SCALP_KEYS


def _daily_loss_limit_inr(config: dict[str, Any], capital: float) -> float:
    if config.get("max_daily_loss_pct") is not None:
        return capital * float(config["max_daily_loss_pct"]) / 100
    return float(config.get("max_loss_per_day") or 5000)


def ensure_session_capital(
    state: dict[str, Any],
    config: dict[str, Any],
    *,
    broker_cash: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Keep session capital in sync with Angel One cash while the desk is flat.
    Freeze the last broker reading while a trade is open so blocked margin
    does not shrink the next size. Returns (updated_state, capital_info).
    """
    today = trading_day_key()
    if state.get("trading_day") != today:
        state["session_start_capital"] = None
        state["session_capital_source"] = None

    manual = float(config.get("capital") or 100_000)
    auto = bool(config.get("auto_capital_from_broker", True))
    utilization_pct = float(config.get("capital_utilization_pct") if config.get("capital_utilization_pct") is not None else 1.0)
    utilization_pct = min(max(utilization_pct, 0.5), 1.0)

    has_open = bool(state.get("active_trades"))
    current = state.get("session_start_capital")
    source = state.get("session_capital_source")
    if auto and broker_cash is not None and float(broker_cash) > 0:
        if not has_open or current is None:
            session_start = round(float(broker_cash), 2)
            source = "broker"
        else:
            session_start = float(current)
            source = source or "broker"
    elif current is None:
        session_start = round(manual, 2)
        source = "manual"
    else:
        session_start = float(current)
        source = source or "manual"

    state["session_start_capital"] = session_start
    state["session_capital_source"] = source
    daily_pnl = float(state.get("daily_pnl") or 0)
    # Live broker cash already reflects closed-trade losses. Only apply the
    # T+1 haircut when we are still on fallback/manual capital.
    if source == "broker" and not has_open:
        after_losses = session_start
    else:
        after_losses = session_start + min(daily_pnl, 0.0)
    deployable = round(max(after_losses, 0.0) * utilization_pct, 2)

    info = {
        "sizing_mode": "utilization",
        "session_start_capital": session_start,
        "session_capital_source": state.get("session_capital_source") or "manual",
        "manual_capital": manual,
        "auto_capital_from_broker": auto,
        "capital_utilization_pct": utilization_pct,
        "daily_pnl": daily_pnl,
        "deployable_capital": deployable,
        "broker_available_cash": round(broker_cash, 2) if broker_cash is not None else None,
        "t_plus_one_note": "Intraday profits credit next day — sizing uses session start capital minus today's losses.",
    }
    return state, info


def compute_utilization_lots(
    instrument_key: str,
    deployable_capital: float,
    option_premium: float,
    *,
    config: dict[str, Any] | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Size lots to use deployable capital against option premium (one trade at a time)."""
    config = config or {}
    state = state or {}
    meta = INSTRUMENTS.get(instrument_key, INSTRUMENTS["nifty50"])
    lot_size = int(meta["lot_size"])
    raw_max_trades = config.get("max_trades_per_day")
    max_trades = 3 if raw_max_trades is None else int(raw_max_trades)
    trade_count = int(state.get("trades_today") or 0)
    open_pnl = float(state.get("daily_pnl") or 0)
    session_start = float(state.get("session_start_capital") or config.get("capital") or 100_000)
    has_open = bool(state.get("active_trades"))

    if has_open:
        return {
            "action": "HALT",
            "lots": 0,
            "capital_at_risk": 0,
            "reason": "open trade active — next entry only after exit",
            "sizing_mode": "utilization",
        }

    if max_trades > 0 and trade_count >= max_trades:
        return {
            "action": "HALT",
            "lots": 0,
            "capital_at_risk": 0,
            "reason": "daily trade limit reached",
            "sizing_mode": "utilization",
        }

    loss_limit = _daily_loss_limit_inr(config, session_start)
    if open_pnl <= -loss_limit:
        return {
            "action": "HALT",
            "lots": 0,
            "capital_at_risk": 0,
            "reason": "daily loss limit hit",
            "sizing_mode": "utilization",
        }

    if option_premium <= 0:
        return {
            "action": "HALT",
            "lots": 0,
            "capital_at_risk": 0,
            "reason": "option premium unavailable — connect broker stream",
            "sizing_mode": "utilization",
        }

    cost_per_lot = option_premium * lot_size
    budget = float(deployable_capital) * (1.0 - CASH_BUFFER_PCT)
    lots = int(budget // cost_per_lot) if cost_per_lot > 0 else 0
    max_lots = int(config.get("max_lots_per_trade") or 0)
    if max_lots > 0:
        lots = min(lots, max_lots)
    freeze_lots = max_lots_per_order(lot_size)
    split_orders = 1
    if lots > freeze_lots:
        split_orders = (lots + freeze_lots - 1) // freeze_lots
    if lots < 1:
        return {
            "action": "HALT",
            "lots": 0,
            "capital_at_risk": 0,
            "reason": "deployable capital too small for one lot at current premium",
            "sizing_mode": "utilization",
            "deployable_capital": deployable_capital,
            "option_premium": round(option_premium, 2),
            "cost_per_lot": round(cost_per_lot, 2),
        }

    capital_deployed = round(lots * cost_per_lot, 2)
    reason = (
        f"{lots} lot(s) · ₹{capital_deployed:,.0f} deployed "
        f"(premium ₹{option_premium:.2f} × {lot_size} × {lots})"
    )
    if split_orders > 1:
        reason += f" · split into {split_orders} orders (exchange freeze {freeze_lots} lots each)"
    return {
        "action": "TRADE",
        "lots": lots,
        "capital_at_risk": capital_deployed,
        "capital_deployed": capital_deployed,
        "deployable_capital": deployable_capital,
        "option_premium": round(option_premium, 2),
        "cost_per_lot": round(cost_per_lot, 2),
        "exchange_freeze_lots": freeze_lots,
        "split_orders": split_orders,
        "sizing_mode": "utilization",
        "reason": reason,
    }


def lots_affordable_from_cash(
    cash: float,
    premium: float,
    lot_size: int,
    *,
    buffer_pct: float = CASH_BUFFER_PCT,
) -> int:
    """Whole lots that fit in cash after a small charges/slippage buffer."""
    lot = max(int(lot_size or 1), 1)
    prem = float(premium or 0)
    if cash <= 0 or prem <= 0:
        return 0
    budget = float(cash) * (1.0 - min(max(buffer_pct, 0.0), 0.2))
    cost = prem * lot
    if cost <= 0:
        return 0
    return int(budget // cost)


def parse_insufficient_funds_amounts(message: str) -> tuple[float | None, float | None]:
    """Parse Angel 'Available funds / You require' amounts from a reject text."""
    match = _INSUFFICIENT_FUNDS_RE.search(str(message or ""))
    if not match:
        return None, None
    try:
        available = float(match.group(1).replace(",", ""))
        required = float(match.group(2).replace(",", ""))
    except (TypeError, ValueError):
        return None, None
    return available, required


def size_index_scalp_from_context(
    instrument_key: str,
    signal: dict[str, Any],
    state: dict[str, Any],
    config: dict[str, Any],
    capital_info: dict[str, Any],
) -> dict[str, Any]:
    """Build utilization sizing from desk signal + capital context."""
    ind = signal.get("indicators") or {}
    premium = float(
        signal.get("entry")
        or ind.get("option_ltp")
        or ind.get("entry_premium")
        or 0
    )
    deployable = float(capital_info.get("deployable_capital") or 0)
    return compute_utilization_lots(
        instrument_key,
        deployable,
        premium,
        config=config,
        state=state,
    )


def estimate_index_option_premium(spot: float, instrument_key: str) -> float:
    """Rough ATM option premium when historical chain is unavailable."""
    if spot <= 0:
        return 100.0
    pct = 0.005 if instrument_key == "nifty50" else 0.006
    return max(spot * pct, 50.0)


def backtest_prior_days_pnl(day_pnl: dict[str, float], current_day: str) -> float:
    return float(sum(pnl for day, pnl in day_pnl.items() if day < current_day))


def backtest_day_session_start(initial_capital: float, prior_days_pnl: float) -> float:
    """Session capital at day open — prior day P&L credits overnight (T+1)."""
    return max(0.0, initial_capital + prior_days_pnl)


def backtest_deployable_capital(
    session_start: float,
    day_pnl_so_far: float,
    utilization_pct: float = 1.0,
) -> float:
    """Deployable margin intraday — losses reduce size; same-day wins do not increase it."""
    pct = min(max(float(utilization_pct if utilization_pct is not None else 1.0), 0.5), 1.0)
    adjusted = session_start + min(float(day_pnl_so_far or 0), 0.0)
    return max(0.0, adjusted * pct)


def backtest_utilization_lots(
    instrument_key: str,
    deployable: float,
    option_premium: float,
) -> int:
    meta = INSTRUMENTS.get(instrument_key, INSTRUMENTS["nifty50"])
    lot_size = int(meta["lot_size"])
    if option_premium <= 0 or deployable <= 0:
        return 0
    cost_per_lot = option_premium * lot_size
    return int(deployable // cost_per_lot) if cost_per_lot > 0 else 0


def backtest_index_trade_pnl(
    signal_type: str,
    entry_spot: float,
    exit_spot: float,
    lot_size: int,
    lots: int,
) -> float:
    move = exit_spot - entry_spot
    pnl = move * lot_size * max(lots, 1)
    if signal_type == "PUT":
        pnl = -pnl
    return pnl


def backtest_option_trade_pnl(
    entry_premium: float,
    exit_premium: float,
    lot_size: int,
    lots: int,
    *,
    order_side: str = "BUY",
) -> float:
    """P&L for long or short option (BUY CE/PE or SELL CE/PE)."""
    from trading_shared.strategies.scalping_desk.option_execution import option_trade_pnl

    return option_trade_pnl(entry_premium, exit_premium, lot_size, lots, order_side=order_side)


def backtest_size_for_bar(
    *,
    initial_capital: float,
    instrument_key: str,
    spot: float,
    day: str,
    day_pnl: dict[str, float],
    utilization_pct: float,
    option_premium: float | None = None,
    max_lots: int = 0,
    current_equity: float | None = None,
) -> tuple[int, float, float]:
    """Return (lots, deployable, premium) for a backtest entry bar.

    When *current_equity* is supplied, size from running account equity (compounding).
    Otherwise fall back to session T+1 rules (losses reduce same-day size; wins do not).
    """
    premium = option_premium if option_premium and option_premium > 0 else estimate_index_option_premium(spot, instrument_key)

    if current_equity is not None:
        deployable = max(0.0, float(current_equity) * min(max(float(utilization_pct or 0.95), 0.5), 1.0))
    else:
        prior = backtest_prior_days_pnl(day_pnl, day)
        session_start = backtest_day_session_start(initial_capital, prior)
        deployable = backtest_deployable_capital(session_start, day_pnl.get(day, 0.0), utilization_pct)

    lots = backtest_utilization_lots(instrument_key, deployable, premium)
    if max_lots and max_lots > 0:
        base = max(float(initial_capital or 0), 1.0)
        pct = min(max(float(utilization_pct or 0.95), 0.5), 1.0)
        lot_cap = max(1, int(round(max_lots * deployable / (base * pct))))
        lots = min(lots, lot_cap)
    return lots, deployable, premium
