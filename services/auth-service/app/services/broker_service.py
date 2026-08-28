import logging

import redis
from fastapi import HTTPException
from sqlalchemy.orm import Session

from trading_shared.broker.angel_one.exceptions import AngelOneAuthError, AngelOneAPIError
from trading_shared.broker.angel_one.session_manager import AngelOneSessionManager
from trading_shared.config import get_settings
from trading_shared.models import User
from trading_shared.schemas.broker import BrokerCredentialRequest

logger = logging.getLogger(__name__)


class BrokerAuthService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.redis = redis.from_url(self.settings.REDIS_URL, decode_responses=True)
        self.session_manager = AngelOneSessionManager(db, self.redis)

    def save_credentials(self, user: User, payload: BrokerCredentialRequest) -> dict:
        try:
            self.session_manager.save_broker_credential(
                user=user,
                api_key=payload.api_key,
                client_code=payload.client_code,
                password=payload.password,
                totp_secret=payload.totp_secret,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        status = self.session_manager.get_connection_status(user.id)
        return {
            "status": "saved",
            "broker": "angel_one",
            "credentials_configured": status.get("credentials_configured", True),
            "client_code": status.get("client_code"),
        }

    async def connect(self, user: User) -> dict:
        try:
            result = await self.session_manager.connect_user(user.id, force=True)
            status = self.session_manager.get_connection_status(user.id)
            return {**status, **result}
        except AngelOneAuthError as exc:
            logger.error("Broker connect failed for user_id=%s: %s", user.id, exc)
            self.session_manager.mark_session_stale(user.id, str(exc))
            status = self.session_manager.get_connection_status(user.id)
            return {**status, "connected": False, "error": str(exc)}

    async def disconnect(self, user: User) -> dict:
        return await self.session_manager.disconnect_user(user.id)

    def status(self, user: User) -> dict:
        return self.session_manager.get_connection_status(user.id)

    async def profile(self, user: User) -> dict:
        client = await self.session_manager.get_client_for_user(user.id)
        return await client.get_profile()

    async def funds(self, user: User) -> dict:
        from trading_shared.broker.angel_one.funds import parse_rms_funds

        if self.session_manager.is_session_stale(user.id):
            return {
                "status": False,
                "message": "Session expired. Reconnect broker.",
                "data": {},
            }

        try:
            client = await self.session_manager.get_client_for_user(user.id)
            raw = await client.get_rms_limits()
            parsed = parse_rms_funds(raw)
            if parsed.get("status"):
                self.session_manager.persist_client_session(user.id, client)
                self.session_manager.clear_session_stale(user.id)
                return parsed

            message = (parsed.get("message") or "").lower()
            if "token" in message or "session" in message or "login" in message:
                client.reset_smart_connect()
                self.session_manager.mark_session_stale(user.id, parsed.get("message") or "invalid_token")
                return {
                    "status": False,
                    "message": "Session expired. Reconnect broker.",
                    "data": {},
                }
            return parsed
        except AngelOneAuthError as exc:
            logger.warning("RMS auth failed for user_id=%s: %s", user.id, exc)
            self.session_manager.mark_session_stale(user.id, str(exc))
            return {
                "status": False,
                "message": "Session expired. Reconnect broker.",
                "data": {},
            }
        except AngelOneAPIError as exc:
            logger.warning("RMS failed for user_id=%s: %s", user.id, exc)
            message = str(exc)
            if "rate limit" in message.lower():
                return {
                    "status": False,
                    "message": message,
                    "data": {},
                }
            lower = message.lower()
            if any(token in lower for token in ("token", "session", "login", "unauthorized", "auth")):
                self.session_manager.mark_session_stale(user.id, message)
                return {
                    "status": False,
                    "message": "Session expired. Reconnect broker.",
                    "data": {},
                }
            return {
                "status": False,
                "message": message,
                "data": {},
            }
        except Exception as exc:
            logger.warning("RMS unexpected failure for user_id=%s: %s", user.id, exc)
            from trading_shared.broker.angel_one.client import normalize_angel_error

            message = normalize_angel_error(str(exc))
            if "rate limit" in message.lower():
                return {"status": False, "message": message, "data": {}}
            lower = message.lower()
            if any(token in lower for token in ("token", "session", "login", "unauthorized", "auth")):
                self.session_manager.mark_session_stale(user.id, message)
                return {
                    "status": False,
                    "message": "Session expired. Reconnect broker.",
                    "data": {},
                }
            return {"status": False, "message": message, "data": {}}

    async def holdings(self, user: User) -> dict:
        client = await self.session_manager.get_client_for_user(user.id)
        return await client.get_holdings()

    async def positions(self, user: User) -> dict:
        client = await self.session_manager.get_client_for_user(user.id)
        return await client.get_positions()

    async def account_snapshot(self, user: User) -> dict:
        from datetime import datetime, timezone

        from trading_shared.broker.angel_one.account_snapshot import (
            normalize_holdings,
            normalize_orders,
            normalize_positions,
            normalize_trades,
        )

        status = self.session_manager.get_connection_status(user.id)
        if not status.get("connected") and not status.get("credentials_configured"):
            return {
                "connected": False,
                "message": "Broker not connected. Connect Angel One to load account data.",
                "orders": [],
                "positions": [],
                "holdings": [],
                "trades": [],
            }

        try:
            client = await self.session_manager.get_client_for_user(user.id)
            orders_resp = await client.get_order_book()
            trades_resp = await client.get_trade_book()
            positions_resp = await client.get_positions()
            holdings_resp = await client.get_holdings()

            orders_raw = orders_resp.get("data") if isinstance(orders_resp, dict) else []
            trades_raw = trades_resp.get("data") if isinstance(trades_resp, dict) else []
            positions_raw = positions_resp.get("data") if isinstance(positions_resp, dict) else []
            holdings_raw = holdings_resp.get("data") if isinstance(holdings_resp, dict) else []

            return {
                "connected": True,
                "message": orders_resp.get("message") if isinstance(orders_resp, dict) else None,
                "orders": normalize_orders(orders_raw if isinstance(orders_raw, list) else []),
                "positions": normalize_positions(positions_raw if isinstance(positions_raw, list) else []),
                "holdings": normalize_holdings(holdings_raw if isinstance(holdings_raw, list) else []),
                "trades": normalize_trades(trades_raw if isinstance(trades_raw, list) else []),
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
        except AngelOneAuthError as exc:
            logger.warning("Account snapshot failed for user_id=%s: %s", user.id, exc)
            self.session_manager.mark_session_stale(user.id, str(exc))
            return {
                "connected": False,
                "message": str(exc),
                "orders": [],
                "positions": [],
                "holdings": [],
                "trades": [],
            }
        except AngelOneAPIError as exc:
            logger.warning("Angel One account snapshot API error user_id=%s: %s", user.id, exc)
            message = str(exc)
            if "rate limit" in message.lower():
                return {
                    "connected": True,
                    "message": message,
                    "orders": [],
                    "positions": [],
                    "holdings": [],
                    "trades": [],
                }
            return {
                "connected": False,
                "message": message,
                "orders": [],
                "positions": [],
                "holdings": [],
                "trades": [],
            }
        except Exception as exc:
            from trading_shared.broker.angel_one.client import normalize_angel_error

            message = normalize_angel_error(str(exc))
            logger.warning("Angel One account snapshot failed user_id=%s: %s", user.id, message)
            return {
                "connected": False,
                "message": message,
                "orders": [],
                "positions": [],
                "holdings": [],
                "trades": [],
            }

    async def cancel_order(self, user: User, order_id: str, variety: str = "NORMAL") -> dict:
        from trading_shared.broker.angel_one.orders import normalize_cancel_variety
        from trading_shared.broker.angel_one.schemas import CancelOrderRequest

        cancel_variety = normalize_cancel_variety(variety)
        try:
            client = await self.session_manager.get_client_for_user(user.id)
            response = await client.cancel_order(
                CancelOrderRequest(variety=cancel_variety, orderid=order_id)
            )
            return {
                "status": "cancelled",
                "order_id": order_id,
                "message": response.get("message") if isinstance(response, dict) else "Order cancelled",
            }
        except AngelOneAuthError as exc:
            self.session_manager.mark_session_stale(user.id, str(exc))
            raise
        except AngelOneAPIError:
            raise

    async def connect_with_env_credentials(self) -> dict:
        """System-level broker connection using environment credentials."""
        if not all([self.settings.ANGEL_API_KEY, self.settings.ANGEL_CLIENT_CODE, self.settings.ANGEL_PASSWORD]):
            return {"connected": False, "error": "Angel One env credentials not configured"}

        from trading_shared.broker.angel_one.client import AngelOneClient

        client = AngelOneClient(
            api_key=self.settings.ANGEL_API_KEY,
            client_code=self.settings.ANGEL_CLIENT_CODE,
            password=self.settings.ANGEL_PASSWORD,
            totp_secret=self.settings.ANGEL_TOTP_SECRET,
            client_local_ip=self.settings.ANGEL_CLIENT_LOCAL_IP,
            client_public_ip=self.settings.ANGEL_CLIENT_PUBLIC_IP,
            mac_address=self.settings.ANGEL_MAC_ADDRESS,
        )
        try:
            logger.info("Angel One system connect starting for client_code=%s", self.settings.ANGEL_CLIENT_CODE)
            result = await client.login()
            await client.verify_session()
            logger.info(
                "Angel One system connect succeeded for client_code=%s expires_at=%s",
                result.get("client_code"),
                result.get("expires_at"),
            )
            self.redis.setex("angel_one:system:session", 3600 * 8, client.to_cache_blob())
            return {"connected": True, **result}
        except (AngelOneAuthError, AngelOneAPIError) as exc:
            logger.error("Angel One system connect failed: %s", exc)
            return {"connected": False, "error": str(exc)}
