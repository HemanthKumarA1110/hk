"""Simulated order execution without Angel One broker connection."""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict

import redis
from sqlalchemy.orm import Session

from trading_shared.broker.angel_one.constants import INDEX_TOKENS
from trading_shared.config import get_settings
from trading_shared.execution.executor import OrderRejectedError, OrderExecutor
from trading_shared.market.redis_bus import MarketRedisBus
from trading_shared.market.scrip_master import ScripMasterService
from trading_shared.models.order import BrokerOrder
from trading_shared.risk.manager import RiskManager
from trading_shared.schemas.order import OrderCreateRequest

logger = logging.getLogger(__name__)

# Demo LTP when market stream / broker is unavailable (paper trading only).
REFERENCE_LTP: dict[str, float] = {
    "NIFTY": 24100.0,
    "BANKNIFTY": 51800.0,
    "RELIANCE-EQ": 1450.0,
    "TCS-EQ": 4100.0,
    "INFY-EQ": 1780.0,
    "HDFCBANK-EQ": 1720.0,
    "SBIN-EQ": 820.0,
    "ITC-EQ": 460.0,
}


class PaperTradeExecutor:
    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self.settings = get_settings()
        self.redis = redis.from_url(self.settings.REDIS_URL, decode_responses=True)
        self.risk = RiskManager(self.settings.REDIS_URL)
        self.scrip = ScripMasterService(self.redis)
        self.market_bus = MarketRedisBus(self.settings.REDIS_URL)

    async def place_order(self, payload: OrderCreateRequest) -> dict:
        symbol, token, exchange = await self._resolve_symbol(
            payload.symbol, payload.exchange, payload.symboltoken
        )

        entry_price = payload.price
        if entry_price <= 0 or payload.order_type.upper() == "MARKET":
            entry_price = self._resolve_price(exchange, symbol, token, payload.price)
        if entry_price <= 0:
            raise OrderRejectedError(
                "Enter a limit price for paper MARKET orders when live quotes are unavailable"
            )

        stoploss = payload.stoploss or self.risk.engine.dynamic_stoploss(
            entry_price, payload.side, atr=entry_price * 0.005
        )
        evaluation = self.risk.evaluate_trade(entry_price, stoploss, payload.side)
        if not evaluation["approved"]:
            self._persist_rejected(payload, symbol, token, exchange, stoploss, evaluation["reason"])
            raise OrderRejectedError(evaluation["reason"])

        approved_qty = min(payload.qty, evaluation["position_size"]["qty"])
        if approved_qty <= 0:
            raise OrderRejectedError("Risk engine returned zero quantity")

        broker_order_id = f"PAPER-{uuid.uuid4().hex[:12].upper()}"
        response = {
            "status": True,
            "message": "Paper order filled (simulated)",
            "data": {"orderid": broker_order_id, "uniqueorderid": broker_order_id},
        }

        order = BrokerOrder(
            user_id=self.user_id,
            broker_order_id=broker_order_id,
            uniqueorderid=broker_order_id,
            symbol=symbol,
            symboltoken=token,
            exchange=exchange,
            side=payload.side.upper(),
            qty=approved_qty,
            price=entry_price,
            order_type=payload.order_type.upper(),
            product=payload.product.upper(),
            variety=payload.variety,
            status="filled",
            stoploss=stoploss,
            risk_approved=True,
            risk_reason=evaluation.get("reason"),
            execution_mode="paper",
            broker_response_json=json.dumps(response),
        )
        self.db.add(order)
        self.db.commit()
        self.db.refresh(order)

        notional = entry_price * approved_qty
        pnl = 0.0
        if payload.side.upper() == "SELL":
            pnl = self._estimate_exit_pnl(symbol, entry_price, approved_qty)
        self.risk.register_trade(pnl, notional)

        return OrderExecutor._serialize_order(order, message=response["message"])

    async def list_trades(self, limit: int = 50) -> list[dict]:
        rows = (
            self.db.query(BrokerOrder)
            .filter(
                BrokerOrder.user_id == self.user_id,
                BrokerOrder.execution_mode == "paper",
                BrokerOrder.status == "filled",
            )
            .order_by(BrokerOrder.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._serialize_paper_row(row) for row in rows]

    def list_all_orders(self, limit: int = 100) -> list[dict]:
        """All paper orders including rejected — for audit/history views."""
        rows = (
            self.db.query(BrokerOrder)
            .filter(
                BrokerOrder.user_id == self.user_id,
                BrokerOrder.execution_mode == "paper",
            )
            .order_by(BrokerOrder.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._serialize_paper_row(row) for row in rows]

    @staticmethod
    def _serialize_paper_row(row: BrokerOrder) -> dict:
        pnl = None
        result = row.status
        if row.status == "filled":
            result = "filled"
        elif row.status == "rejected_by_risk":
            result = "rejected"
        return {
            "source": "live_trading",
            "order_id": row.broker_order_id or str(row.id),
            "symbol": row.symbol,
            "side": row.side,
            "qty": row.qty,
            "price": row.price,
            "entry": row.price,
            "exit": None,
            "pnl": pnl,
            "status": row.status,
            "result": result,
            "risk_approved": row.risk_approved,
            "risk_reason": row.risk_reason,
            "timestamp": row.created_at.isoformat() if row.created_at else None,
            "mode": "paper",
            "instrument": row.exchange,
        }

    def list_positions(self) -> list[dict]:
        rows = (
            self.db.query(BrokerOrder)
            .filter(
                BrokerOrder.user_id == self.user_id,
                BrokerOrder.execution_mode == "paper",
                BrokerOrder.status == "filled",
            )
            .order_by(BrokerOrder.created_at.asc())
            .all()
        )
        net_qty: dict[str, int] = defaultdict(int)
        cost_basis: dict[str, float] = defaultdict(float)
        for row in rows:
            signed_qty = row.qty if row.side == "BUY" else -row.qty
            if signed_qty > 0:
                cost_basis[row.symbol] += row.price * signed_qty
                net_qty[row.symbol] += signed_qty
            else:
                net_qty[row.symbol] += signed_qty
                if net_qty[row.symbol] == 0:
                    cost_basis[row.symbol] = 0.0

        positions = []
        for symbol, qty in net_qty.items():
            if qty == 0:
                continue
            avg = cost_basis[symbol] / qty if qty else 0.0
            positions.append(
                {
                    "symbol": symbol,
                    "qty": qty,
                    "side": "LONG" if qty > 0 else "SHORT",
                    "avg_price": round(avg, 2),
                    "mode": "paper",
                }
            )
        return positions

    def _estimate_exit_pnl(self, symbol: str, exit_price: float, qty: int) -> float:
        buys = (
            self.db.query(BrokerOrder)
            .filter(
                BrokerOrder.user_id == self.user_id,
                BrokerOrder.execution_mode == "paper",
                BrokerOrder.symbol == symbol,
                BrokerOrder.side == "BUY",
                BrokerOrder.status == "filled",
            )
            .order_by(BrokerOrder.created_at.asc())
            .all()
        )
        if not buys:
            return 0.0
        entry = buys[-1].price
        return (exit_price - entry) * qty

    async def _resolve_symbol(
        self, raw_symbol: str, exchange: str, symboltoken: str | None = None
    ) -> tuple[str, str, str]:
        cleaned = raw_symbol.strip().upper()
        if ":" in cleaned:
            exchange, cleaned = cleaned.split(":", 1)
        cleaned = cleaned.replace(" ", "")
        if cleaned in ("NIFTY", "BANKNIFTY"):
            meta = INDEX_TOKENS[cleaned]
            return meta["tradingsymbol"], meta["symboltoken"], meta["exchange"]

        if not cleaned.endswith("-EQ") and exchange == "NSE":
            cleaned_eq = f"{cleaned}-EQ"
        else:
            cleaned_eq = cleaned

        try:
            await self.scrip.refresh(force=False)
            if symboltoken:
                inst = self.scrip.get_by_token(symboltoken)
                if inst:
                    return inst.symbol, inst.token, inst.exchange or exchange

            inst = self.scrip.get_equity_by_symbol(cleaned_eq, exchange=exchange)
            if inst:
                return inst.symbol, inst.token, inst.exchange or exchange

            matches = self.scrip.search_equity(cleaned.replace("-EQ", ""), exchange=exchange, limit=1)
            if matches:
                inst = matches[0]
                return inst.symbol, inst.token, inst.exchange or exchange
        except Exception:
            logger.debug("Scrip master lookup failed for %s", raw_symbol)

        if cleaned_eq in REFERENCE_LTP:
            return cleaned_eq, "0", exchange

        raise OrderRejectedError(f"Unable to resolve symbol {raw_symbol} for paper trading")

    def _resolve_price(self, exchange: str, symbol: str, token: str, limit_price: float) -> float:
        if limit_price > 0:
            return limit_price

        tick = self.market_bus.get_tick(1, token)
        if tick and tick.get("ltp"):
            return float(tick["ltp"])

        for key, price in REFERENCE_LTP.items():
            if key in symbol.upper() or symbol.upper() in key:
                return price

        return 0.0

    def _persist_rejected(
        self,
        payload: OrderCreateRequest,
        symbol: str,
        token: str,
        exchange: str,
        stoploss: float,
        reason: str,
    ) -> BrokerOrder:
        order = BrokerOrder(
            user_id=self.user_id,
            symbol=symbol,
            symboltoken=token,
            exchange=exchange,
            side=payload.side.upper(),
            qty=payload.qty,
            price=payload.price,
            order_type=payload.order_type.upper(),
            product=payload.product.upper(),
            variety=payload.variety,
            status="rejected_by_risk",
            stoploss=stoploss,
            risk_approved=False,
            risk_reason=reason,
            execution_mode="paper",
        )
        self.db.add(order)
        self.db.commit()
        self.db.refresh(order)
        return order
