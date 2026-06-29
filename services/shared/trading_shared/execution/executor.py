"""Risk-gated order execution against Angel One."""

from __future__ import annotations

import json
import logging

import redis
from sqlalchemy.orm import Session

from trading_shared.broker.angel_one.exceptions import AngelOneAPIError, AngelOneAuthError
from trading_shared.broker.angel_one.schemas import (
    CancelOrderRequest,
    LTPRequest,
    ModifyOrderRequest,
    PlaceOrderRequest,
    SearchScripRequest,
)
from trading_shared.broker.angel_one.session_manager import AngelOneSessionManager
from trading_shared.config import get_settings
from trading_shared.market.scrip_master import ScripMasterService
from trading_shared.models.order import BrokerOrder
from trading_shared.risk.manager import RiskManager
from trading_shared.schemas.order import OrderCancelRequest as CancelPayload
from trading_shared.schemas.order import OrderCreateRequest, OrderModifyRequest

logger = logging.getLogger(__name__)


class OrderRejectedError(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class OrderExecutor:
    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self.settings = get_settings()
        self.redis = redis.from_url(self.settings.REDIS_URL, decode_responses=True)
        self.session_manager = AngelOneSessionManager(db, self.redis)
        self.risk = RiskManager(self.settings.REDIS_URL)
        self.scrip = ScripMasterService(self.redis)

    async def place_order(self, payload: OrderCreateRequest) -> dict:
        client = await self.session_manager.get_client_for_user(self.user_id)
        symbol, token, exchange = await self._resolve_symbol(
            client, payload.symbol, payload.exchange, payload.symboltoken
        )

        entry_price = payload.price
        reference_price = payload.price if payload.price and payload.price > 0 else None
        if payload.order_type.upper() == "MARKET":
            if reference_price:
                entry_price = reference_price
            else:
                entry_price = await self._fetch_ltp(client, exchange, symbol, token)
        elif entry_price <= 0:
            entry_price = await self._fetch_ltp(client, exchange, symbol, token)

        stoploss = payload.stoploss or self.risk.engine.dynamic_stoploss(
            entry_price, payload.side, atr=entry_price * 0.005
        )
        evaluation = self.risk.evaluate_trade(entry_price, stoploss, payload.side)
        if not evaluation["approved"]:
            order = self._persist_rejected(payload, symbol, token, exchange, stoploss, evaluation["reason"])
            raise OrderRejectedError(evaluation["reason"])

        approved_qty = min(payload.qty, evaluation["position_size"]["qty"])
        if approved_qty <= 0:
            raise OrderRejectedError("Risk engine returned zero quantity")

        place_req = PlaceOrderRequest(
            variety=payload.variety,
            tradingsymbol=symbol,
            symboltoken=token,
            transactiontype=payload.side.upper(),
            exchange=exchange,
            ordertype="MARKET" if payload.order_type.upper() == "MARKET" else "LIMIT",
            producttype=self._map_product(payload.product),
            duration="DAY",
            price=str(payload.price if payload.order_type.upper() == "LIMIT" else 0),
            quantity=str(approved_qty),
            stoploss=str(stoploss),
        )

        try:
            response = await client.place_order(place_req)
        except AngelOneAPIError as exc:
            logger.exception("Broker order failed")
            raise

        broker_order_id = self._extract_order_id(response)
        order = BrokerOrder(
            user_id=self.user_id,
            broker_order_id=broker_order_id,
            uniqueorderid=response.get("data", {}).get("uniqueorderid") if isinstance(response.get("data"), dict) else None,
            symbol=symbol,
            symboltoken=token,
            exchange=exchange,
            side=payload.side.upper(),
            qty=approved_qty,
            price=entry_price,
            order_type=place_req.ordertype,
            product=payload.product.upper(),
            variety=payload.variety,
            status="submitted",
            stoploss=stoploss,
            risk_approved=True,
            risk_reason=evaluation.get("reason"),
            execution_mode="live",
            broker_response_json=json.dumps(response),
        )
        self.db.add(order)
        self.db.commit()
        self.db.refresh(order)

        notional = entry_price * approved_qty
        self.risk.register_trade(0.0, notional)

        return self._serialize_order(order, message=response.get("message", "Order placed"))

    async def modify_order(self, payload: OrderModifyRequest) -> dict:
        client = await self.session_manager.get_client_for_user(self.user_id)
        response = await client.modify_order(
            ModifyOrderRequest(
                variety=payload.variety,
                orderid=payload.order_id,
                ordertype=payload.order_type,
                price=str(payload.price) if payload.price is not None else None,
                quantity=str(payload.qty) if payload.qty is not None else None,
                triggerprice=str(payload.trigger_price) if payload.trigger_price is not None else None,
            )
        )
        order = (
            self.db.query(BrokerOrder)
            .filter(
                BrokerOrder.user_id == self.user_id,
                BrokerOrder.broker_order_id == payload.order_id,
            )
            .first()
        )
        if order:
            order.status = "modified"
            order.broker_response_json = json.dumps(response)
            self.db.commit()
        return {"status": "modified", "response": response}

    async def cancel_order(self, payload: CancelPayload) -> dict:
        client = await self.session_manager.get_client_for_user(self.user_id)
        response = await client.cancel_order(
            CancelOrderRequest(variety=payload.variety, orderid=payload.order_id)
        )
        order = (
            self.db.query(BrokerOrder)
            .filter(
                BrokerOrder.user_id == self.user_id,
                BrokerOrder.broker_order_id == payload.order_id,
            )
            .first()
        )
        if order:
            order.status = "cancelled"
            order.broker_response_json = json.dumps(response)
            self.db.commit()
        return {"status": "cancelled", "response": response}

    async def list_orders(self, limit: int = 50) -> list[dict]:
        rows = (
            self.db.query(BrokerOrder)
            .filter(BrokerOrder.user_id == self.user_id)
            .order_by(BrokerOrder.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._serialize_order(row) for row in rows]

    async def sync_order_book(self) -> dict:
        client = await self.session_manager.get_client_for_user(self.user_id)
        book = await client.get_order_book()
        return book

    async def trade_book(self) -> list[dict]:
        client = await self.session_manager.get_client_for_user(self.user_id)
        book = await client.get_trade_book()
        trades = book.get("data") or []
        normalized = []
        for row in trades:
            normalized.append(
                {
                    "symbol": row.get("tradingsymbol") or row.get("symbol"),
                    "side": row.get("transactiontype") or row.get("side"),
                    "qty": int(float(row.get("quantity") or row.get("qty") or 0)),
                    "price": float(row.get("price") or row.get("fillprice") or 0),
                    "status": row.get("status") or "executed",
                    "timestamp": row.get("filltime") or row.get("updatetime"),
                    "order_id": row.get("orderid"),
                }
            )
        return normalized

    async def _resolve_symbol(
        self, client, raw_symbol: str, exchange: str, symboltoken: str | None = None
    ) -> tuple[str, str, str]:
        cleaned = raw_symbol.strip().upper()
        if ":" in cleaned:
            exchange, cleaned = cleaned.split(":", 1)
        cleaned = cleaned.replace(" ", "")
        if not cleaned.endswith("-EQ") and exchange == "NSE" and not cleaned.endswith("CE") and not cleaned.endswith("PE"):
            cleaned_eq = f"{cleaned}-EQ"
        else:
            cleaned_eq = cleaned

        try:
            self.scrip.ensure_loaded()
            if symboltoken:
                inst = self.scrip.get_by_token(symboltoken)
                if inst:
                    return inst.symbol, inst.token, inst.exchange or exchange

            inst = self.scrip.get_equity_by_symbol(cleaned_eq, exchange=exchange)
            if inst:
                return inst.symbol, inst.token, inst.exchange or exchange

            matches = self.scrip.search_equity(cleaned.replace("-EQ", ""), exchange=exchange, limit=5)
            if matches:
                inst = matches[0]
                return inst.symbol, inst.token, inst.exchange or exchange
        except RuntimeError:
            logger.debug("Scrip master unavailable during symbol resolution for %s", raw_symbol)

        search = await client.search_scrip(SearchScripRequest(exchange=exchange, searchscrip=cleaned.replace("-EQ", "")))
        data = search.get("data") or []
        for row in data:
            tradingsymbol = str(row.get("tradingsymbol") or "")
            if tradingsymbol.endswith("-EQ"):
                return tradingsymbol, str(row.get("symboltoken", "")), exchange
        if data:
            row = data[0]
            return row.get("tradingsymbol", cleaned_eq), str(row.get("symboltoken", "")), exchange

        if cleaned in ("NIFTY", "BANKNIFTY"):
            inst = self.scrip.index_token(cleaned)
            if inst:
                return inst.symbol, inst.token, "NSE"

        raise AngelOneAuthError(f"Unable to resolve symbol token for {raw_symbol}")

    async def _fetch_ltp(self, client, exchange: str, symbol: str, token: str) -> float:
        from trading_shared.market.index_quotes import extract_ltp_from_response

        response = await client.get_ltp(LTPRequest(exchange=exchange, tradingsymbol=symbol, symboltoken=token))
        ltp = extract_ltp_from_response(response, token)
        if ltp is not None and ltp > 0:
            return ltp
        message = response.get("message") if isinstance(response, dict) else None
        raise AngelOneAPIError(message or "Unable to fetch LTP for risk evaluation")

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
        )
        self.db.add(order)
        self.db.commit()
        self.db.refresh(order)
        return order

    @staticmethod
    def _map_product(product: str) -> str:
        mapping = {
            "INTRADAY": "INTRADAY",
            "DELIVERY": "DELIVERY",
            "MARGIN": "MARGIN",
            "CNC": "DELIVERY",
            "MIS": "INTRADAY",
        }
        return mapping.get(product.upper(), "INTRADAY")

    @staticmethod
    def _extract_order_id(response: dict) -> str | None:
        data = response.get("data")
        if isinstance(data, dict):
            return str(data.get("orderid") or data.get("order_id") or "")
        if data:
            return str(data)
        return None

    @staticmethod
    def _serialize_order(order: BrokerOrder, message: str | None = None) -> dict:
        return {
            "id": order.id,
            "broker_order_id": order.broker_order_id,
            "symbol": order.symbol,
            "side": order.side,
            "qty": order.qty,
            "price": order.price,
            "order_type": order.order_type,
            "product": order.product,
            "status": order.status,
            "message": message,
            "risk_approved": order.risk_approved,
            "risk_reason": order.risk_reason,
            "execution_mode": order.execution_mode,
            "created_at": order.created_at.isoformat() if order.created_at else None,
        }
