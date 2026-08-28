"""Simulated order execution using Angel One live quotes — no broker placement."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import redis
from sqlalchemy.orm import Session

from trading_shared.broker.angel_one.constants import INDEX_TOKENS
from trading_shared.broker.angel_one.exceptions import AngelOneAPIError, AngelOneAuthError
from trading_shared.broker.angel_one.schemas import LTPRequest
from trading_shared.broker.angel_one.session_manager import AngelOneSessionManager
from trading_shared.config import get_settings
from trading_shared.execution.executor import OrderRejectedError
from trading_shared.market.constants import NSE_CM, NSE_FO
from trading_shared.market.index_quotes import extract_ltp_from_response
from trading_shared.market.redis_bus import MarketRedisBus
from trading_shared.market.scrip_master import ScripMasterService
from trading_shared.models.order import BrokerOrder
from trading_shared.risk.manager import RiskManager
from trading_shared.schemas.order import OrderCreateRequest

logger = logging.getLogger(__name__)


def _parse_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {"response": {}, "meta": {}}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"response": {}, "meta": {}}
    if isinstance(data, dict) and "meta" in data:
        return {"response": data.get("response") or {}, "meta": data.get("meta") or {}}
    return {"response": data if isinstance(data, dict) else {}, "meta": {}}


def _dump_payload(response: dict[str, Any], meta: dict[str, Any]) -> str:
    return json.dumps({"response": response, "meta": meta})


def _desk_to_source(desk: str | None) -> str:
    """Map desk tag from order meta to a stable source id for the paper orders UI."""
    if not desk:
        return "live_trading"
    key = str(desk).strip().lower()
    if key.startswith("scalping"):
        return "scalping_desk"
    if key == "intraday":
        return "intraday_desk"
    if key == "swing":
        return "swing_desk"
    return "live_trading"


def _infer_source_from_order(row: BrokerOrder, desk: str | None) -> str:
    """Resolve source for legacy rows saved before desk tags were persisted."""
    tagged = _desk_to_source(desk)
    if tagged != "live_trading":
        return tagged
    exchange = str(row.exchange or "").upper()
    product = str(row.product or "").upper()
    if exchange == "NFO":
        return "scalping_desk"
    if product == "DELIVERY" and exchange == "NSE":
        return "swing_desk"
    if product == "INTRADAY" and exchange == "NSE":
        return "intraday_desk"
    return "live_trading"


def _source_label(source: str | None) -> str:
    labels = {
        "scalping_desk": "Scalping",
        "intraday_desk": "Intraday",
        "swing_desk": "Swing",
        "live_trading": "Live form",
    }
    return labels.get(str(source or ""), "Platform")


class PaperTradeExecutor:
    """Paper trading mirrors live logic but stores dummy orders updated from live market data."""

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self.settings = get_settings()
        self.redis = redis.from_url(self.settings.REDIS_URL, decode_responses=True)
        self.risk = RiskManager(self.settings.REDIS_URL)
        self.scrip = ScripMasterService(self.redis)
        self.market_bus = MarketRedisBus(self.settings.REDIS_URL)
        self.session_manager = AngelOneSessionManager(db, self.redis)

    async def place_order(
        self,
        payload: OrderCreateRequest,
        *,
        desk: str | None = None,
        strategy_code: str | None = None,
    ) -> dict:
        symbol, token, exchange = await self._resolve_symbol(
            payload.symbol, payload.exchange, payload.symboltoken
        )

        entry_price, quote_source = await self._resolve_live_price(exchange, symbol, token, payload.price)
        stoploss = payload.stoploss or self.risk.engine.dynamic_stoploss(
            entry_price, payload.side, atr=entry_price * 0.005
        )
        desk_driven = bool(desk and str(desk).strip())
        if desk_driven:
            can_trade, halt_reason = self.risk.engine.can_trade()
            if not can_trade:
                raise OrderRejectedError(halt_reason or "Trading halted")
            if payload.qty <= 0:
                raise OrderRejectedError("Invalid quantity from desk")
            approved_qty = int(payload.qty)
            evaluation = {
                "approved": True,
                "reason": "desk_sized",
                "position_size": {"qty": approved_qty},
            }
        else:
            evaluation = self.risk.evaluate_trade(entry_price, stoploss, payload.side)
            if not evaluation["approved"]:
                reason = evaluation["reason"]
                if reason == "ok" and int(evaluation["position_size"].get("qty") or 0) <= 0:
                    reason = (
                        evaluation["position_size"].get("message")
                        or "Risk capital allocation full — close open paper positions or reset session"
                    )
                raise OrderRejectedError(reason)
            approved_qty = min(payload.qty, evaluation["position_size"]["qty"])
            if approved_qty <= 0:
                raise OrderRejectedError("Risk engine returned zero quantity")

        broker_order_id = f"PAPER-{uuid.uuid4().hex[:12].upper()}"
        now_iso = datetime.now(timezone.utc).isoformat()
        meta = {
            "quote_source": quote_source,
            "entry_ltp": entry_price,
            "live_ltp": entry_price,
            "unrealized_pnl": 0.0,
            "realized_pnl": None,
            "exit_ltp": None,
            "exit_reason": None,
            "desk": desk,
            "strategy_code": strategy_code,
            "opened_at": now_iso,
            "updated_at": now_iso,
        }
        response = {
            "status": True,
            "message": "Paper order opened at live market price (simulated)",
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
            status="open",
            stoploss=stoploss,
            risk_approved=True,
            risk_reason=evaluation.get("reason"),
            execution_mode="paper",
            broker_response_json=_dump_payload(response, meta),
        )
        self.db.add(order)
        self.db.commit()
        self.db.refresh(order)

        notional = entry_price * approved_qty
        self.risk.register_trade(0.0, notional)

        return self._serialize_order(order, message=response["message"])

    async def close_open_order(
        self,
        *,
        broker_order_id: str | None = None,
        symbol: str | None = None,
        exit_price: float | None = None,
        reason: str = "",
    ) -> dict | None:
        query = self.db.query(BrokerOrder).filter(
            BrokerOrder.user_id == self.user_id,
            BrokerOrder.execution_mode == "paper",
            BrokerOrder.status == "open",
        )
        if broker_order_id:
            query = query.filter(BrokerOrder.broker_order_id == broker_order_id)
        elif symbol:
            query = query.filter(BrokerOrder.symbol == symbol)
        else:
            return None

        order = query.order_by(BrokerOrder.created_at.desc()).first()
        if not order:
            return None

        if exit_price is None or exit_price <= 0:
            exit_price, quote_source = await self._resolve_live_price(
                order.exchange, order.symbol, order.symboltoken, 0
            )
        else:
            quote_source = "signal"

        pnl = self._calc_pnl(order.side, order.price, exit_price, order.qty)
        payload = _parse_payload(order.broker_response_json)
        meta = payload["meta"]
        meta.update(
            {
                "exit_ltp": exit_price,
                "exit_reason": reason,
                "realized_pnl": round(pnl, 2),
                "unrealized_pnl": 0.0,
                "live_ltp": exit_price,
                "quote_source": quote_source,
                "closed_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        order.status = "closed"
        order.broker_response_json = _dump_payload(payload["response"], meta)
        self.db.commit()
        self.db.refresh(order)
        release_notional = float(order.price) * int(order.qty)
        self.risk.register_trade(pnl, -release_notional)
        return self._serialize_order(order, message="Paper position closed at live price (simulated)")

    async def close_eod_open_orders(self) -> int:
        """Force-close open paper orders after the 3:15 PM IST market cutoff."""
        from trading_shared.strategies.scalping_desk.constants import FORCE_EXIT_HOUR_IST
        from zoneinfo import ZoneInfo

        now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
        force_exit = now_ist.hour > FORCE_EXIT_HOUR_IST[0] or (
            now_ist.hour == FORCE_EXIT_HOUR_IST[0] and now_ist.minute >= FORCE_EXIT_HOUR_IST[1]
        )
        if not force_exit:
            return 0

        rows = (
            self.db.query(BrokerOrder)
            .filter(
                BrokerOrder.user_id == self.user_id,
                BrokerOrder.execution_mode == "paper",
                BrokerOrder.status == "open",
            )
            .order_by(BrokerOrder.created_at.asc())
            .all()
        )
        closed = 0
        for row in rows:
            try:
                result = await self.close_open_order(
                    broker_order_id=row.broker_order_id,
                    reason="market_close_eod",
                )
                if result:
                    closed += 1
            except Exception:
                logger.exception("EOD paper close failed for %s", row.broker_order_id)
        return closed

    async def refresh_open_orders(self) -> list[dict]:
        interval = int(getattr(self.settings, "PAPER_QUOTE_REFRESH_SEC", 30))
        throttle_key = f"paper:quote_refresh:{self.user_id}"
        if self.redis.get(throttle_key):
            return self._serialize_open_rows()

        rows = (
            self.db.query(BrokerOrder)
            .filter(
                BrokerOrder.user_id == self.user_id,
                BrokerOrder.execution_mode == "paper",
                BrokerOrder.status == "open",
            )
            .order_by(BrokerOrder.created_at.asc())
            .all()
        )
        updated: list[dict] = []
        for row in rows:
            payload = _parse_payload(row.broker_response_json)
            meta = payload["meta"]
            try:
                live_ltp, quote_source = await self._resolve_live_price(
                    row.exchange, row.symbol, row.symboltoken, 0, cached_ltp=meta.get("live_ltp")
                )
            except OrderRejectedError:
                cached = meta.get("live_ltp") or row.price
                if cached:
                    live_ltp = float(cached)
                    quote_source = "cached"
                else:
                    continue
            meta["live_ltp"] = live_ltp
            meta["quote_source"] = quote_source
            meta["unrealized_pnl"] = round(self._calc_pnl(row.side, row.price, live_ltp, row.qty), 2)
            meta["updated_at"] = datetime.now(timezone.utc).isoformat()
            row.broker_response_json = _dump_payload(payload["response"], meta)
            updated.append(self._serialize_paper_row(row))
        if updated:
            self.db.commit()
        self.redis.setex(throttle_key, interval, "1")
        return updated or self._serialize_open_rows()

    def _serialize_open_rows(self) -> list[dict]:
        rows = (
            self.db.query(BrokerOrder)
            .filter(
                BrokerOrder.user_id == self.user_id,
                BrokerOrder.execution_mode == "paper",
                BrokerOrder.status == "open",
            )
            .order_by(BrokerOrder.created_at.asc())
            .all()
        )
        return [self._serialize_paper_row(row) for row in rows]

    async def list_trades(self, limit: int = 50) -> list[dict]:
        rows = (
            self.db.query(BrokerOrder)
            .filter(
                BrokerOrder.user_id == self.user_id,
                BrokerOrder.execution_mode == "paper",
                BrokerOrder.status.in_(("open", "closed")),
            )
            .order_by(BrokerOrder.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._serialize_paper_row(row) for row in rows]

    def list_all_orders(self, limit: int = 100) -> list[dict]:
        rows = (
            self.db.query(BrokerOrder)
            .filter(
                BrokerOrder.user_id == self.user_id,
                BrokerOrder.execution_mode == "paper",
                BrokerOrder.status.in_(("open", "closed")),
            )
            .order_by(BrokerOrder.created_at.desc())
            .limit(limit)
            .all()
        )
        return [self._serialize_paper_row(row) for row in rows]

    def list_positions(self) -> list[dict]:
        rows = (
            self.db.query(BrokerOrder)
            .filter(
                BrokerOrder.user_id == self.user_id,
                BrokerOrder.execution_mode == "paper",
                BrokerOrder.status == "open",
            )
            .order_by(BrokerOrder.created_at.asc())
            .all()
        )
        net_qty: dict[str, int] = defaultdict(int)
        cost_basis: dict[str, float] = defaultdict(float)
        live_ltp: dict[str, float] = {}
        unrealized: dict[str, float] = defaultdict(float)

        for row in rows:
            payload = _parse_payload(row.broker_response_json)
            meta = payload["meta"]
            signed_qty = row.qty if row.side == "BUY" else -row.qty
            net_qty[row.symbol] += signed_qty
            if signed_qty > 0:
                cost_basis[row.symbol] += row.price * signed_qty
            if meta.get("live_ltp"):
                live_ltp[row.symbol] = float(meta["live_ltp"])
            unrealized[row.symbol] += float(meta.get("unrealized_pnl") or 0)

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
                    "live_ltp": live_ltp.get(symbol),
                    "unrealized_pnl": round(unrealized.get(symbol, 0), 2),
                    "mode": "paper",
                    "status": "open",
                }
            )
        return positions

    async def _resolve_live_price(
        self,
        exchange: str,
        symbol: str,
        token: str,
        limit_price: float,
        *,
        cached_ltp: float | None = None,
    ) -> tuple[float, str]:
        if limit_price and limit_price > 0:
            return float(limit_price), "limit"

        exchange_type = NSE_FO if exchange.upper() == "NFO" else NSE_CM
        tick = self.market_bus.get_tick(exchange_type, token)
        if tick and tick.get("ltp"):
            return float(tick["ltp"]), "angel_stream"

        if exchange.upper() != "NFO":
            tick = self.market_bus.get_tick(NSE_CM, token)
            if tick and tick.get("ltp"):
                return float(tick["ltp"]), "angel_stream"

        try:
            client = await self.session_manager.get_client_for_user(self.user_id)
            response = await client.get_ltp(
                LTPRequest(exchange=exchange, tradingsymbol=symbol, symboltoken=token)
            )
            ltp = extract_ltp_from_response(response, token)
            if ltp is not None and ltp > 0:
                return float(ltp), "angel_ltp"
        except (AngelOneAuthError, AngelOneAPIError, TypeError, ValueError):
            logger.debug("Angel LTP fetch failed for %s", symbol, exc_info=True)

        if cached_ltp and float(cached_ltp) > 0:
            return float(cached_ltp), "cached"

        raise OrderRejectedError(
            "Live market price unavailable. Connect Angel One and start the market stream for paper trading."
        )

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

        if symboltoken:
            return cleaned_eq, str(symboltoken), exchange

        raise OrderRejectedError(f"Unable to resolve symbol {raw_symbol} for paper trading")

    @staticmethod
    def _calc_pnl(side: str, entry: float, mark: float, qty: int) -> float:
        move = (mark - entry) * qty
        return -move if side.upper() == "SELL" else move

    def _serialize_order(self, order: BrokerOrder, *, message: str) -> dict:
        row = self._serialize_paper_row(order)
        row["message"] = message
        row["id"] = order.id
        row["broker_order_id"] = order.broker_order_id
        return row

    @staticmethod
    def _serialize_paper_row(row: BrokerOrder) -> dict:
        payload = _parse_payload(row.broker_response_json)
        meta = payload["meta"]
        pnl = meta.get("realized_pnl")
        if pnl is None and row.status == "open":
            pnl = meta.get("unrealized_pnl")
        result = row.status
        if row.status == "closed" and pnl is not None:
            result = "win" if float(pnl) > 0 else "loss" if float(pnl) < 0 else "breakeven"
        desk = meta.get("desk")
        source = _infer_source_from_order(row, desk)
        return {
            "source": source,
            "source_label": _source_label(source),
            "order_id": row.broker_order_id or str(row.id),
            "symbol": row.symbol,
            "side": row.side,
            "qty": row.qty,
            "price": row.price,
            "entry": row.price,
            "exit": meta.get("exit_ltp"),
            "live_ltp": meta.get("live_ltp"),
            "pnl": round(float(pnl), 2) if pnl is not None else None,
            "status": row.status,
            "result": result,
            "risk_approved": row.risk_approved,
            "risk_reason": row.risk_reason,
            "timestamp": row.created_at.isoformat() if row.created_at else None,
            "updated_at": meta.get("updated_at") or (row.updated_at.isoformat() if row.updated_at else None),
            "mode": "paper",
            "instrument": row.exchange,
            "quote_source": meta.get("quote_source"),
            "desk": desk,
            "strategy_code": meta.get("strategy_code"),
            "exit_reason": meta.get("exit_reason"),
        }

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


async def refresh_all_paper_orders(db: Session) -> dict[str, int]:
    user_ids = [
        row[0]
        for row in db.query(BrokerOrder.user_id)
        .filter(BrokerOrder.execution_mode == "paper", BrokerOrder.status == "open")
        .distinct()
        .all()
    ]
    refreshed = 0
    eod_closed = 0
    for user_id in user_ids:
        try:
            executor = PaperTradeExecutor(db, user_id)
            updated = await executor.refresh_open_orders()
            refreshed += len(updated)
            eod_closed += await executor.close_eod_open_orders()
        except Exception:
            logger.exception("Paper quote refresh failed for user_id=%s", user_id)
    return {"users": len(user_ids), "orders_refreshed": refreshed, "eod_closed": eod_closed}


def refresh_all_paper_orders_sync(db: Session) -> dict[str, int]:
    return asyncio.run(refresh_all_paper_orders(db))
