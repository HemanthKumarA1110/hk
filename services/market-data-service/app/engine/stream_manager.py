"""Central live stream orchestrator for Angel One SmartAPI."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import redis
from sqlalchemy.orm import Session

from trading_shared.broker.angel_one.session_manager import AngelOneSessionManager
from trading_shared.config import get_settings
from trading_shared.db.session import SessionLocal
from trading_shared.market.analytics import black_scholes_greeks, compute_pcr, parse_tick
from trading_shared.market.scrip_master import (
    REDIS_SCRIP_UPDATED_KEY,
    ScripMasterService,
    parse_option_strike_symbol,
)
from trading_shared.market.websocket_stream import AngelOneWebSocketStream
from trading_shared.models import MarketCandle, OptionChainSnapshot

from trading_shared.market.constants import REDIS_STREAM_DESIRED_KEY
from trading_shared.market.redis_bus import MarketRedisBus
from trading_shared.market.scanner import MarketScanner
from app.engine.candle_builder import CandleBuilder

logger = logging.getLogger(__name__)

STREAM_DESIRED_ON = "on"
STREAM_DESIRED_OFF = "off"


class StreamStartError(Exception):
    """Raised when live market stream cannot be started."""


class StreamManager:
    _instance: "StreamManager | None" = None

    def __init__(self):
        settings = get_settings()
        self.settings = settings
        self.redis_bus = MarketRedisBus(settings.REDIS_URL)
        self.redis_raw = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.scrip_service = ScripMasterService(self.redis_raw)
        self.candle_builder = CandleBuilder()
        self.scanner = MarketScanner(self.redis_bus, self.scrip_service)
        self.stream: AngelOneWebSocketStream | None = None
        self.ticks_received = 0
        self.last_tick_at: datetime | None = None
        self.scanner_task: asyncio.Task | None = None
        self._token_symbol_map: dict[str, str] = {}
        self._running = False

    @classmethod
    def get(cls) -> "StreamManager":
        if cls._instance is None:
            cls._instance = StreamManager()
        return cls._instance

    async def start(self) -> dict[str, Any]:
        self.set_desired(True)
        if self._running and self.stream and self.stream.connected:
            return self._status_with_message("Live stream already connected")

        if self._running:
            await self.stop()

        try:
            if not self.scrip_service.ensure_loaded():
                await self.scrip_service.refresh(force=True)
        except Exception as exc:
            logger.warning("Scrip master refresh failed during stream start: %s", exc)
            if not self.scrip_service.ensure_loaded():
                raise StreamStartError(
                    "Scrip master unavailable. Retry after broker connect or check network."
                ) from exc

        session = self._load_system_session()
        if not session:
            raise StreamStartError("No Angel One session found. Connect broker from Live Trading first.")
        if not session.get("jwt_token"):
            raise StreamStartError("Broker JWT missing. Reconnect Angel One and try again.")
        if not session.get("feed_token"):
            raise StreamStartError(
                "Feed token missing. Disconnect and reconnect Angel One to enable live streaming."
            )

        api_key = session.get("api_key") or self.settings.ANGEL_API_KEY
        if not api_key:
            raise StreamStartError(
                "API key missing for websocket. Save broker credentials or set ANGEL_API_KEY."
            )

        nse_cm_tokens, nse_fo_tokens, self._token_symbol_map = self._build_subscription_universe()
        if not nse_cm_tokens and not nse_fo_tokens:
            raise StreamStartError("No subscription tokens available from scrip master.")

        token_groups = AngelOneWebSocketStream.build_token_groups(nse_cm_tokens, nse_fo_tokens)
        self.stream = AngelOneWebSocketStream(
            auth_token=session["jwt_token"],
            api_key=api_key,
            client_code=session["client_code"],
            feed_token=session["feed_token"],
            on_tick=self._handle_tick,
        )
        self.stream.set_subscriptions(token_groups)
        try:
            self.stream.start()
        except Exception as exc:
            self.stream = None
            raise StreamStartError(
                f"WebSocket failed to start: {exc}. Reconnect Angel One and try again."
            ) from exc
        self._running = True
        self.scanner_task = asyncio.create_task(self._scanner_loop())

        for _ in range(10):
            await asyncio.sleep(0.5)
            if self.stream.connected:
                break

        status = self._status_with_message(
            "Live stream connected"
            if self.stream.connected
            else "Stream started but websocket not connected yet — check feed token and retry"
        )
        self.redis_bus.store_stream_status(status)
        logger.info(
            "Market stream started connected=%s cm=%s fo=%s",
            self.stream.connected,
            len(nse_cm_tokens),
            len(nse_fo_tokens),
        )
        return status

    async def stop(self) -> dict[str, Any]:
        self.set_desired(False)
        self._running = False
        if self.scanner_task:
            self.scanner_task.cancel()
        if self.stream:
            self.stream.stop()
            self.stream = None
        status = self._status_with_message("Live market stream stopped")
        self.redis_bus.store_stream_status(status)
        return status

    def is_desired(self) -> bool:
        return self.redis_raw.get(REDIS_STREAM_DESIRED_KEY) == STREAM_DESIRED_ON

    def set_desired(self, enabled: bool) -> None:
        self.redis_raw.set(REDIS_STREAM_DESIRED_KEY, STREAM_DESIRED_ON if enabled else STREAM_DESIRED_OFF)

    def status(self) -> dict[str, Any]:
        return self._status_with_message(None)

    def _status_with_message(self, message: str | None) -> dict[str, Any]:
        subscriptions = 0
        if self.stream and self.stream._subscriptions:
            for group in self.stream._subscriptions:
                subscriptions += len(group.get("tokens", []))
        desired = self.is_desired()
        payload = {
            "connected": bool(self.stream and self.stream.connected),
            "desired": desired,
            "enabled": desired,
            "subscriptions": subscriptions,
            "ticks_received": self.ticks_received,
            "last_tick_at": self.last_tick_at.isoformat() if self.last_tick_at else None,
            "scanner_running": self._running,
            "scrip_master_updated_at": self.redis_raw.get(REDIS_SCRIP_UPDATED_KEY),
        }
        if message:
            payload["message"] = message
        return payload

    def _resolve_user_id(self, client_code: str | None) -> int | None:
        if not client_code:
            return None
        db = SessionLocal()
        try:
            from trading_shared.models import BrokerSession

            session = (
                db.query(BrokerSession)
                .filter(
                    BrokerSession.client_code == client_code,
                    BrokerSession.is_active.is_(True),
                )
                .order_by(BrokerSession.created_at.desc())
                .first()
            )
            return session.user_id if session else None
        finally:
            db.close()

    def _resolve_api_key(self, user_id: int | None) -> str:
        if self.settings.ANGEL_API_KEY:
            return self.settings.ANGEL_API_KEY
        if not user_id:
            return ""
        db = SessionLocal()
        try:
            from trading_shared.models import BrokerCredential
            from trading_shared.security.encryption import decrypt_value

            cred = (
                db.query(BrokerCredential)
                .filter(BrokerCredential.user_id == user_id, BrokerCredential.is_active.is_(True))
                .first()
            )
            if cred:
                return decrypt_value(cred.encrypted_api_key, self.settings.ENCRYPTION_KEY)
        except Exception:
            logger.exception("Failed to resolve API key for user_id=%s", user_id)
        finally:
            db.close()
        return ""

    def _load_system_session(self) -> dict[str, Any] | None:
        blob = self.redis_raw.get("angel_one:system:session")
        if blob:
            payload = json.loads(blob)
            had_api_key = bool(payload.get("api_key") or self.settings.ANGEL_API_KEY)
            api_key = payload.get("api_key") or self.settings.ANGEL_API_KEY
            if not api_key:
                user_id = payload.get("user_id") or self._resolve_user_id(payload.get("client_code"))
                api_key = self._resolve_api_key(user_id)
            payload["api_key"] = api_key
            if api_key and not had_api_key:
                self.redis_raw.setex("angel_one:system:session", 3600 * 8, json.dumps(payload))
            return payload

        db = SessionLocal()
        try:
            from trading_shared.models import BrokerSession

            session = (
                db.query(BrokerSession)
                .filter(BrokerSession.is_active.is_(True))
                .order_by(BrokerSession.created_at.desc())
                .first()
            )
            if not session:
                return None
            return {
                "jwt_token": session.jwt_token,
                "refresh_token": session.refresh_token,
                "feed_token": session.feed_token,
                "client_code": session.client_code,
                "api_key": self._resolve_api_key(session.user_id),
            }
        finally:
            db.close()

    def _build_subscription_universe(self) -> tuple[list[str], list[str], dict[str, str]]:
        token_symbol: dict[str, str] = {}
        nse_cm: list[str] = []
        nse_fo: list[str] = []

        for index in ("NIFTY", "BANKNIFTY"):
            inst = self.scrip_service.index_token(index)
            if inst:
                nse_cm.append(inst.token)
                token_symbol[inst.token] = index

        for inst in self.scrip_service.nifty50_equities():
            nse_cm.append(inst.token)
            token_symbol[inst.token] = inst.symbol

        nifty_inst = self.scrip_service.index_token("NIFTY")
        bank_inst = self.scrip_service.index_token("BANKNIFTY")
        nifty_spot = 24000.0
        bank_spot = 52000.0
        if nifty_inst:
            tick = self.redis_bus.get_tick(1, nifty_inst.token)
            if tick:
                nifty_spot = tick.get("ltp", nifty_spot)
        if bank_inst:
            tick = self.redis_bus.get_tick(1, bank_inst.token)
            if tick:
                bank_spot = tick.get("ltp", bank_spot)

        for underlying, spot in (("NIFTY", nifty_spot), ("BANKNIFTY", bank_spot)):
            for inst in self.scrip_service.nearest_expiry_options(underlying, spot, strike_window=5):
                nse_fo.append(inst.token)
                token_symbol[inst.token] = inst.symbol
            for inst in self.scrip_service.futures_chain(underlying, count=2):
                nse_fo.append(inst.token)
                token_symbol[inst.token] = inst.symbol

        # Angel One allows max 50 tokens per subscription batch; trim if needed
        nse_cm = list(dict.fromkeys(nse_cm))[:40]
        nse_fo = list(dict.fromkeys(nse_fo))[:50]
        return nse_cm, nse_fo, token_symbol

    def _handle_tick(self, raw: dict[str, Any]) -> None:
        tick = parse_tick(raw)
        token = tick["token"]
        symbol = self._token_symbol_map.get(token)
        if not symbol:
            inst = self.scrip_service.get_by_token(token)
            symbol = inst.symbol if inst else token
            self._token_symbol_map[token] = symbol
        tick["symbol"] = symbol

        exchange_type = tick.get("exchange_type", 1)
        self.redis_bus.store_tick(exchange_type, token, tick)
        self.redis_bus.publish_tick(tick)

        completed = self.candle_builder.ingest(token, symbol, tick["ltp"], tick.get("volume", 0))
        for candle in completed:
            self.redis_bus.store_candle(token, candle["interval"], candle)
            self._persist_candle(candle)

        self.ticks_received += 1
        self.last_tick_at = datetime.now(timezone.utc)
        if self.ticks_received % 100 == 0:
            self.redis_bus.store_stream_status(self.status())

        if symbol.endswith("CE") or symbol.endswith("PE") or "FUT" in symbol:
            self._update_option_chain_snapshot(symbol, tick)

    def _persist_candle(self, candle: dict[str, Any]) -> None:
        db = SessionLocal()
        try:
            db.add(
                MarketCandle(
                    token=candle["token"],
                    symbol=candle["symbol"],
                    exchange="NSE",
                    interval=candle["interval"],
                    candle_ts=datetime.fromisoformat(candle["candle_ts"]),
                    open=candle["open"],
                    high=candle["high"],
                    low=candle["low"],
                    close=candle["close"],
                    volume=candle["volume"],
                    vwap=candle.get("vwap"),
                )
            )
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def _update_option_chain_snapshot(self, symbol: str, tick: dict[str, Any]) -> None:
        underlying = "NIFTY" if "NIFTY" in symbol and "BANKNIFTY" not in symbol else "BANKNIFTY"
        chain = self.redis_bus.get_option_chain(underlying) or {
            "underlying": underlying,
            "expiry": "",
            "spot": 0,
            "rows": {},
            "total_ce_oi": 0,
            "total_pe_oi": 0,
        }
        existing_rows = chain.get("rows")
        if isinstance(existing_rows, dict):
            rows = existing_rows
        elif isinstance(existing_rows, list):
            rows = {
                row["symbol"]: row
                for row in existing_rows
                if isinstance(row, dict) and row.get("symbol")
            }
        else:
            rows = {}
        chain["rows"] = rows
        strike = parse_option_strike_symbol(symbol)
        rows[symbol] = {
            "symbol": symbol,
            "token": tick["token"],
            "ltp": tick["ltp"],
            "oi": tick.get("oi", 0),
            "volume": tick.get("volume", 0),
            **({"strike": strike} if strike is not None else {}),
        }
        total_ce_oi = sum(row["oi"] for key, row in rows.items() if key.endswith("CE"))
        total_pe_oi = sum(row["oi"] for key, row in rows.items() if key.endswith("PE"))
        chain["total_ce_oi"] = total_ce_oi
        chain["total_pe_oi"] = total_pe_oi
        chain["pcr"] = compute_pcr(total_ce_oi, total_pe_oi)
        self.redis_bus.store_option_chain(underlying, chain)

    async def _scanner_loop(self) -> None:
        while self._running:
            try:
                db = SessionLocal()
                try:
                    self.scanner.run_scan(db)
                    await self._build_option_chain_metrics()
                finally:
                    db.close()
            except Exception:
                logger.exception("Scanner loop failed")
            await asyncio.sleep(30)

    async def _build_option_chain_metrics(self) -> None:
        for underlying in ("NIFTY", "BANKNIFTY"):
            chain = self.redis_bus.get_option_chain(underlying)
            if not chain:
                continue
            index_inst = self.scrip_service.index_token(underlying)
            spot = 0.0
            if index_inst:
                tick = self.redis_bus.get_tick(1, index_inst.token)
                spot = tick.get("ltp", 0) if tick else 0
            rows = []
            for symbol, row in chain.get("rows", {}).items():
                strike = parse_option_strike_symbol(symbol) or 0.0
                opt_type = "CE" if symbol.endswith("CE") else "PE"
                iv = 0.18
                greeks = black_scholes_greeks(spot, strike, 7 / 365, 0.07, iv, opt_type)
                rows.append(
                    {
                        **row,
                        "strike": strike,
                        "option_type": opt_type,
                        "iv": greeks.iv,
                        "delta": greeks.delta,
                        "gamma": greeks.gamma,
                        "theta": greeks.theta,
                        "vega": greeks.vega,
                    }
                )
            payload = {
                "underlying": underlying,
                "expiry": chain.get("expiry", ""),
                "spot": spot,
                "pcr": chain.get("pcr"),
                "total_ce_oi": chain.get("total_ce_oi", 0),
                "total_pe_oi": chain.get("total_pe_oi", 0),
                "rows": rows,
            }
            self.redis_bus.store_option_chain(underlying, payload)
            db = SessionLocal()
            try:
                db.add(
                    OptionChainSnapshot(
                        underlying=underlying,
                        expiry=chain.get("expiry", ""),
                        pcr=chain.get("pcr"),
                        total_ce_oi=chain.get("total_ce_oi", 0),
                        total_pe_oi=chain.get("total_pe_oi", 0),
                        payload=json.dumps(payload),
                    )
                )
                db.commit()
            except Exception:
                db.rollback()
            finally:
                db.close()

    async def fetch_historical_candles(
        self,
        db: Session,
        user_id: int,
        exchange: str,
        symboltoken: str,
        interval: str,
        fromdate: str,
        todate: str,
    ) -> dict[str, Any]:
        from trading_shared.broker.angel_one.schemas import CandleRequest
        from trading_shared.broker.angel_one.session_manager import AngelOneSessionManager

        manager = AngelOneSessionManager(db, self.redis_raw)
        client = await manager.get_client_for_user(user_id)
        api_interval = {
            "1m": "ONE_MINUTE",
            "3m": "THREE_MINUTE",
            "5m": "FIVE_MINUTE",
            "15m": "FIFTEEN_MINUTE",
            "1d": "ONE_DAY",
        }.get(interval, "ONE_MINUTE")
        return await client.get_candles(
            CandleRequest(
                exchange=exchange,
                symboltoken=symboltoken,
                interval=api_interval,
                fromdate=fromdate,
                todate=todate,
            )
        )
