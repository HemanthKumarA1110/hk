"""Background refresh of open paper orders from live Angel One quotes."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from trading_shared.db.session import SessionLocal
from trading_shared.execution.paper import refresh_all_paper_orders_sync

logger = logging.getLogger(__name__)


def sync_paper_orders_sync() -> dict:
    db: Session = SessionLocal()
    try:
        return refresh_all_paper_orders_sync(db)
    finally:
        db.close()
