"""Portfolio sync from Angel One holdings and positions."""

from __future__ import annotations

import logging

import redis
from sqlalchemy.orm import Session

from trading_shared.broker.angel_one.exceptions import AngelOneAuthError
from trading_shared.broker.angel_one.session_manager import AngelOneSessionManager
from trading_shared.config import get_settings

logger = logging.getLogger(__name__)


class PortfolioSync:
    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self.settings = get_settings()
        self.redis = redis.from_url(self.settings.REDIS_URL, decode_responses=True)
        self.session_manager = AngelOneSessionManager(db, self.redis)

    async def summary(self) -> dict:
        try:
            client = await self.session_manager.get_client_for_user(self.user_id)
            positions_resp = await client.get_positions()
            holdings_resp = await client.get_holdings()
            positions = self._normalize_positions(positions_resp.get("data") or [])
            holdings = self._normalize_holdings(holdings_resp.get("data") or [])
            day_pnl = sum(float(p.get("pnl", 0) or 0) for p in positions)
            total_value = sum(float(h.get("currentvalue", 0) or 0) for h in holdings)
            total_value += sum(abs(float(p.get("netvalue", 0) or 0)) for p in positions)
            return {
                "status": "live",
                "positions": positions + holdings,
                "day_pnl": round(day_pnl, 2),
                "total_value": round(total_value, 2),
                "position_count": len(positions),
                "holding_count": len(holdings),
            }
        except AngelOneAuthError:
            return {"status": "disconnected", "positions": [], "day_pnl": 0, "total_value": 0}

    async def positions(self) -> dict:
        summary = await self.summary()
        return {"positions": summary.get("positions", []), "status": summary.get("status")}

    @staticmethod
    def _normalize_positions(rows: list) -> list[dict]:
        result = []
        for row in rows:
            qty = int(float(row.get("netqty") or row.get("quantity") or 0))
            if qty == 0:
                continue
            result.append(
                {
                    "symbol": row.get("tradingsymbol") or row.get("symbol"),
                    "qty": qty,
                    "avg_price": float(row.get("averageprice") or row.get("avgprice") or 0),
                    "ltp": float(row.get("ltp") or 0),
                    "pnl": float(row.get("pnl") or row.get("unrealised") or 0),
                    "product": row.get("producttype") or row.get("product"),
                    "type": "position",
                }
            )
        return result

    @staticmethod
    def _normalize_holdings(rows: list) -> list[dict]:
        result = []
        for row in rows:
            qty = int(float(row.get("quantity") or 0))
            if qty == 0:
                continue
            result.append(
                {
                    "symbol": row.get("tradingsymbol") or row.get("symbol"),
                    "qty": qty,
                    "avg_price": float(row.get("averageprice") or 0),
                    "ltp": float(row.get("ltp") or 0),
                    "pnl": float(row.get("profitandloss") or 0),
                    "current_value": float(row.get("currentvalue") or 0),
                    "type": "holding",
                }
            )
        return result
