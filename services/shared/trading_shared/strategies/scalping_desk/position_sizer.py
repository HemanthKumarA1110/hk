"""
Dynamic position sizing for the scalping desk AI / risk layer.

Implements the battle-tested sizing rules (deterministic). The prompt template
is available for LLM-backed extensions via `format_position_sizer_prompt`.
"""

from __future__ import annotations

from typing import Any

from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS
from trading_shared.strategies.scalping_desk.capital_utilization import (
    ensure_session_capital,
    is_index_scalp_desk,
    size_index_scalp_from_context,
)

POSITION_SIZER_PROMPT = """You are a risk manager for an algorithmic trading bot. Calculate the optimal position size for this trade.

Account details:
- Total capital: ₹{CAPITAL}
- Current open P&L today: ₹{OPEN_PNL}
- Trades taken today: {TRADE_COUNT}
- Max daily loss limit: {MAX_DAILY_LOSS_PCT}% of capital
- Risk per trade: {RISK_PER_TRADE_PCT}% of capital

Trade details:
- Instrument: {INSTRUMENT}
- Entry: {ENTRY}
- Stop loss: {SL}
- Lot size: {LOT_SIZE}
- Points at risk per lot: {ENTRY} - {SL} = {RISK_PTS} pts

Rules to apply:
1. If trades taken today >= 3, return {{"action":"HALT","reason":"daily trade limit reached"}}
2. If open P&L <= -({MAX_DAILY_LOSS_PCT}% × capital), return {{"action":"HALT","reason":"daily loss limit hit"}}
3. After 2 consecutive losses, halve the normal position size
4. Never exceed available capital on a single trade (full deployable utilization for index desks)

Return JSON: {{"action":"TRADE|HALT","lots":0,"capital_at_risk":0,"reason":""}}"""


def format_position_sizer_prompt(
    *,
    capital: float,
    open_pnl: float,
    trade_count: int,
    max_daily_loss_pct: float,
    risk_per_trade_pct: float,
    instrument: str,
    entry: float,
    stop_loss: float,
    lot_size: int,
    risk_pts: float | None = None,
) -> str:
    pts = risk_pts if risk_pts is not None else abs(entry - stop_loss)
    return POSITION_SIZER_PROMPT.format(
        CAPITAL=round(capital, 2),
        OPEN_PNL=round(open_pnl, 2),
        TRADE_COUNT=trade_count,
        MAX_DAILY_LOSS_PCT=max_daily_loss_pct,
        RISK_PER_TRADE_PCT=risk_per_trade_pct,
        INSTRUMENT=instrument,
        ENTRY=entry,
        SL=stop_loss,
        LOT_SIZE=lot_size,
        RISK_PTS=round(pts, 2),
    )


def _resolve_risk_pct(config: dict[str, Any], capital: float) -> tuple[float, float]:
    """Return (max_daily_loss_pct, risk_per_trade_pct)."""
    risk_per_trade_pct = float(config.get("risk_per_trade_pct") or config.get("params", {}).get("risk_per_trade_pct") or 1.0)
    if config.get("max_daily_loss_pct") is not None:
        max_daily_loss_pct = float(config["max_daily_loss_pct"])
    else:
        max_loss_inr = float(config.get("max_loss_per_day") or 5000)
        max_daily_loss_pct = round(max_loss_inr / max(capital, 1) * 100, 2)
    return max_daily_loss_pct, risk_per_trade_pct


def compute_dynamic_position_size(
    *,
    instrument_key: str,
    capital: float,
    open_pnl: float,
    trade_count: int,
    consecutive_losses: int,
    entry: float,
    stop_loss: float,
    config: dict[str, Any] | None = None,
    risk_pts: float | None = None,
    max_lots: int = 2,
    max_trades_per_day: int = 3,
) -> dict[str, Any]:
    """
    Deterministic position sizer matching POSITION_SIZER_PROMPT rules.

    Returns:
        {"action": "TRADE"|"HALT", "lots": int, "capital_at_risk": float, "reason": str, ...}
    """
    config = config or {}
    meta = INSTRUMENTS.get(instrument_key, INSTRUMENTS["nifty50"])
    lot_size = int(meta["lot_size"])
    max_daily_loss_pct, risk_per_trade_pct = _resolve_risk_pct(config, capital)
    raw_max_trades = config.get("max_trades_per_day")
    max_trades = max_trades_per_day if raw_max_trades is None else int(raw_max_trades)
    max_lots = int(config.get("max_lots_per_trade") or max_lots)

    instrument_label = meta.get("label") or instrument_key.upper()
    pts = float(risk_pts if risk_pts is not None else abs(entry - stop_loss))

    prompt = format_position_sizer_prompt(
        capital=capital,
        open_pnl=open_pnl,
        trade_count=trade_count,
        max_daily_loss_pct=max_daily_loss_pct,
        risk_per_trade_pct=risk_per_trade_pct,
        instrument=instrument_label,
        entry=entry,
        stop_loss=stop_loss,
        lot_size=lot_size,
        risk_pts=pts,
    )

    if max_trades > 0 and trade_count >= max_trades:
        return {
            "action": "HALT",
            "lots": 0,
            "capital_at_risk": 0,
            "reason": "daily trade limit reached",
            "prompt": prompt,
            "max_trades_per_day": max_trades,
        }

    daily_loss_limit_inr = capital * (max_daily_loss_pct / 100)
    if open_pnl <= -daily_loss_limit_inr:
        return {
            "action": "HALT",
            "lots": 0,
            "capital_at_risk": 0,
            "reason": "daily loss limit hit",
            "prompt": prompt,
            "daily_loss_limit_inr": round(daily_loss_limit_inr, 2),
        }

    if pts <= 0:
        return {
            "action": "HALT",
            "lots": 0,
            "capital_at_risk": 0,
            "reason": "invalid stop — zero points at risk",
            "prompt": prompt,
        }

    risk_budget_inr = capital * (risk_per_trade_pct / 100)
    risk_per_lot_inr = pts * lot_size
    raw_lots = int(risk_budget_inr // risk_per_lot_inr) if risk_per_lot_inr > 0 else 0

    if raw_lots < 1:
        return {
            "action": "HALT",
            "lots": 0,
            "capital_at_risk": 0,
            "reason": "risk budget too small for one lot at this stop",
            "prompt": prompt,
            "risk_budget_inr": round(risk_budget_inr, 2),
            "risk_per_lot_inr": round(risk_per_lot_inr, 2),
        }

    lots = min(raw_lots, max_lots)
    if consecutive_losses >= 2:
        lots = max(1, lots // 2)
        reason = f"{lots} lot(s) after {consecutive_losses} consecutive losses (half size)"
    else:
        reason = f"{lots} lot(s) at {risk_per_trade_pct}% capital risk"

    capital_at_risk = round(lots * risk_per_lot_inr, 2)

    return {
        "action": "TRADE",
        "lots": lots,
        "capital_at_risk": capital_at_risk,
        "reason": reason,
        "prompt": prompt,
        "risk_budget_inr": round(risk_budget_inr, 2),
        "risk_per_lot_inr": round(risk_per_lot_inr, 2),
        "risk_pts": round(pts, 2),
        "max_lots_cap": max_lots,
        "consecutive_losses": consecutive_losses,
    }


def size_from_signal_context(
    instrument_key: str,
    signal: dict[str, Any],
    state: dict[str, Any],
    config: dict[str, Any],
    targets: dict[str, Any] | None = None,
    *,
    capital_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build sizer inputs from desk signal + state."""
    if is_index_scalp_desk(instrument_key):
        if capital_info is None:
            _, capital_info = ensure_session_capital(state, config)
        return size_index_scalp_from_context(
            instrument_key, signal, state, config, capital_info
        )

    ind = signal.get("indicators") or {}
    capital = float(config.get("capital") or 100_000)
    entry = float(signal.get("entry") or ind.get("spot") or 0)
    stop_loss = float(signal.get("stoploss") or 0)
    stop_pts = float(
        (targets or {}).get("stop_pts")
        or ind.get("index_stop_pts")
        or signal.get("stop_pts")
        or 0
    )
    return compute_dynamic_position_size(
        instrument_key=instrument_key,
        capital=capital,
        open_pnl=float(state.get("daily_pnl") or 0),
        trade_count=int(state.get("trades_today") or 0),
        consecutive_losses=int(state.get("consecutive_losses") or 0),
        entry=entry,
        stop_loss=stop_loss,
        config=config,
        risk_pts=stop_pts if stop_pts > 0 else None,
    )
