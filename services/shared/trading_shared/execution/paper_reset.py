"""Reset paper trading session — orders, desk state, and daily P&L counters."""

from __future__ import annotations

from datetime import date
from typing import Any

import redis
from sqlalchemy.orm import Session

from trading_shared.config import get_settings
from trading_shared.models.order import BrokerOrder
from trading_shared.risk.manager import RiskManager
from trading_shared.strategies.intraday_desk.service import (
    REDIS_STATE_PREFIX as INTRADAY_STATE_PREFIX,
    IntradayDeskService,
)
from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS, REDIS_DESK_PREFIX, REDIS_STATE_SUFFIX
from trading_shared.strategies.scalping_desk.service import ScalpingDeskService
from trading_shared.strategies.swing_desk.service import (
    REDIS_STATE_PREFIX as SWING_STATE_PREFIX,
    SwingDeskService,
)


def reset_paper_trading_session(db: Session, user_id: int) -> dict[str, Any]:
    """Clear all paper orders and desk trading state for the user."""
    open_rows = (
        db.query(BrokerOrder)
        .filter(
            BrokerOrder.user_id == user_id,
            BrokerOrder.execution_mode == "paper",
            BrokerOrder.status == "open",
        )
        .all()
    )
    open_notional = sum(float(row.price or 0) * int(row.qty or 0) for row in open_rows)

    deleted_orders = (
        db.query(BrokerOrder)
        .filter(BrokerOrder.user_id == user_id, BrokerOrder.execution_mode == "paper")
        .delete(synchronize_session=False)
    )
    db.commit()

    if open_notional > 0:
        risk = RiskManager(get_settings().REDIS_URL)
        risk.engine.state.exposure = max(0.0, risk.engine.state.exposure - open_notional)
        risk.save()

    settings = get_settings()
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    desks_reset: list[str] = []

    for instrument_key in INSTRUMENTS:
        state_key = f"{REDIS_DESK_PREFIX}:{user_id}:{instrument_key}:{REDIS_STATE_SUFFIX}"
        client.delete(state_key)
        desks_reset.append(f"scalping:{instrument_key}")

    client.delete(f"{INTRADAY_STATE_PREFIX}:{user_id}")
    client.delete(f"{SWING_STATE_PREFIX}:{user_id}")
    desks_reset.extend(["intraday", "swing"])

    for instrument_key in INSTRUMENTS:
        ScalpingDeskService(db, user_id, instrument_key).get_state()
    IntradayDeskService(db, user_id).get_state()
    SwingDeskService(db, user_id).get_state()

    return {
        "ok": True,
        "deleted_orders": int(deleted_orders or 0),
        "desks_reset": desks_reset,
        "day": date.today().isoformat(),
        "message": "Paper trading session reset — orders and desk P&L cleared.",
    }
