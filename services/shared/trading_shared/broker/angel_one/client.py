"""Production Angel One SmartAPI client with session management and retry logic."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pyotp
from SmartApi import SmartConnect

from trading_shared.broker.angel_one.constants import ROOT_URL, ROUTES
from trading_shared.broker.angel_one.exceptions import AngelOneAPIError, AngelOneAuthError
from trading_shared.broker.angel_one.schemas import (
    CancelOrderRequest,
    CandleRequest,
    LTPRequest,
    ModifyOrderRequest,
    PlaceOrderRequest,
    SearchScripRequest,
)

logger = logging.getLogger(__name__)


class AngelOneClient:
    """Async-first Angel One SmartAPI wrapper with sync compatibility."""

    def __init__(
        self,
        api_key: str,
        client_code: str = "",
        password: str = "",
        totp_secret: str = "",
        client_local_ip: str = "127.0.0.1",
        client_public_ip: str = "127.0.0.1",
        mac_address: str = "00:00:00:00:00:00",
    ):
        self.api_key = api_key
        self.client_code = client_code
        self.password = password
        self.totp_secret = totp_secret
        self.client_local_ip = client_local_ip
        self.client_public_ip = client_public_ip
        self.mac_address = mac_address

        self.jwt_token: str | None = None
        self.refresh_token: str | None = None
        self.feed_token: str | None = None
        self._smart_connect: SmartConnect | None = None
        self._session_expires_at: datetime | None = None

    def _base_headers(self, authenticated: bool = False) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": self.client_local_ip,
            "X-ClientPublicIP": self.client_public_ip,
            "X-MACAddress": self.mac_address,
            "X-PrivateKey": self.api_key,
        }
        if authenticated and self.jwt_token:
            headers["Authorization"] = f"Bearer {self._normalize_bearer_token(self.jwt_token)}"
        return headers

    def _normalize_totp_secret(self, secret: str) -> str:
        return secret.replace(" ", "").strip().upper()

    def generate_totp(self) -> str:
        """Generate a live 6-digit OTP from the stored Base32 TOTP secret."""
        secret = self._normalize_totp_secret(self.totp_secret)
        if not secret:
            raise AngelOneAuthError("TOTP secret is required for Angel One login")
        otp = pyotp.TOTP(secret).now()
        if len(otp) != 6 or not otp.isdigit():
            raise AngelOneAuthError("Failed to generate a valid 6-digit OTP from TOTP secret")
        logger.info(
            "Generated live Angel One OTP for client_code=%s (otp_length=%s)",
            self.client_code or "unknown",
            len(otp),
        )
        return otp

    @staticmethod
    def _normalize_bearer_token(token: str | None) -> str | None:
        if not token:
            return None
        cleaned = token.strip()
        if cleaned.lower().startswith("bearer "):
            cleaned = cleaned[7:].strip()
        return cleaned or None

    def _create_smart_connect(self) -> SmartConnect:
        return SmartConnect(
            api_key=self.api_key,
            clientLocalIP=self.client_local_ip,
            clientPublicIP=self.client_public_ip,
            clientMacAddress=self.mac_address,
        )

    def _ensure_smart_connect(self) -> SmartConnect:
        if self._smart_connect is None:
            self._smart_connect = self._create_smart_connect()
        if self.jwt_token:
            self._smart_connect.setAccessToken(self._normalize_bearer_token(self.jwt_token))
        if self.refresh_token:
            self._smart_connect.setRefreshToken(self.refresh_token)
        return self._smart_connect

    def reset_smart_connect(self) -> None:
        self._smart_connect = None

    async def login(
        self,
        client_code: str | None = None,
        password: str | None = None,
        totp: str | None = None,
    ) -> dict[str, Any]:
        client_code = client_code or self.client_code
        password = password or self.password

        if totp and len(totp.strip()) == 6 and totp.strip().isdigit():
            otp = totp.strip()
            logger.info(
                "Using provided 6-digit OTP for Angel One login client_code=%s",
                client_code,
            )
        else:
            if totp:
                logger.warning(
                    "Ignoring invalid OTP argument for client_code=%s; generating live OTP from TOTP secret",
                    client_code,
                )
            otp = self.generate_totp()

        if not all([self.api_key, client_code, password, otp]):
            raise AngelOneAuthError("API key, client code, password, and OTP are required")

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, self._login_sync, client_code, password, otp)
        return response

    def _login_sync(self, client_code: str, password: str, otp: str) -> dict[str, Any]:
        logger.info("Angel One generateSession starting for client_code=%s", client_code)
        smart = self._create_smart_connect()
        try:
            result = smart.generateSession(client_code, password, otp)
        except Exception as exc:
            logger.error(
                "Angel One generateSession exception for client_code=%s: %s",
                client_code,
                exc,
            )
            raise AngelOneAuthError(str(exc)) from exc

        if not result or not result.get("status"):
            message = result.get("message", "Angel One login failed") if isinstance(result, dict) else "Angel One login failed"
            logger.error(
                "Angel One generateSession error for client_code=%s: %s response=%s",
                client_code,
                message,
                result,
            )
            raise AngelOneAuthError(message)

        data = result.get("data") or {}
        jwt_token = self._normalize_bearer_token(smart.access_token) or self._normalize_bearer_token(
            data.get("jwtToken")
        )
        refresh_token = smart.refresh_token or data.get("refreshToken")
        logger.info(
            "Angel One generateSession token response for client_code=%s: jwt_present=%s refresh_present=%s feed_token_in_response=%s",
            client_code,
            bool(jwt_token),
            bool(refresh_token),
            bool(data.get("feedToken")),
        )
        self.jwt_token = jwt_token
        self.refresh_token = refresh_token
        if not self.jwt_token or not self.refresh_token:
            logger.error(
                "Angel One generateSession missing tokens for client_code=%s response=%s",
                client_code,
                result,
            )
            raise AngelOneAuthError("Angel One login response missing tokens")
        self.client_code = client_code
        self._smart_connect = smart
        self._smart_connect.setAccessToken(self.jwt_token)
        self._smart_connect.setRefreshToken(self.refresh_token)

        try:
            self.feed_token = smart.getfeedToken() or self._normalize_bearer_token(data.get("feedToken"))
        except Exception as exc:
            logger.warning("Feed token fetch failed: %s", exc)
            self.feed_token = None

        self._session_expires_at = datetime.now(timezone.utc).replace(hour=18, minute=30, second=0, microsecond=0)
        if self._session_expires_at <= datetime.now(timezone.utc):
            self._session_expires_at += timedelta(days=1)

        return {
            "status": True,
            "jwt_token": self.jwt_token,
            "refresh_token": self.refresh_token,
            "feed_token": self.feed_token,
            "client_code": client_code,
            "expires_at": self._session_expires_at.isoformat(),
        }

    async def refresh_session(self) -> dict[str, Any]:
        if not self.refresh_token:
            raise AngelOneAuthError("Refresh token unavailable")

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._refresh_sync)

    def _refresh_sync(self) -> dict[str, Any]:
        logger.info("Angel One token refresh starting for client_code=%s", self.client_code)
        smart = self._ensure_smart_connect()
        try:
            result = smart.generateToken(self.refresh_token)
        except Exception as exc:
            logger.error(
                "Angel One token refresh exception for client_code=%s: %s",
                self.client_code,
                exc,
            )
            raise AngelOneAuthError(str(exc)) from exc
        if not isinstance(result, dict):
            raise AngelOneAuthError("Token refresh failed")
        if result.get("success") is False or result.get("status") is False:
            raise AngelOneAuthError(result.get("message", "Token refresh failed"))

        data = result.get("data")
        if not isinstance(data, dict) or not data.get("jwtToken"):
            raise AngelOneAuthError(result.get("message", "Token refresh response missing jwtToken"))
        logger.info(
            "Angel One token refresh response for client_code=%s: jwt_present=%s refresh_present=%s",
            self.client_code,
            bool(data.get("jwtToken")),
            bool(data.get("refreshToken")),
        )
        self.jwt_token = self._normalize_bearer_token(data["jwtToken"])
        self.refresh_token = data.get("refreshToken", self.refresh_token)
        smart.setAccessToken(self.jwt_token)
        smart.setRefreshToken(self.refresh_token)
        return {"status": True, "jwt_token": self.jwt_token, "refresh_token": self.refresh_token}

    async def ensure_session(self) -> None:
        if self.jwt_token and self._session_expires_at and datetime.now(timezone.utc) < self._session_expires_at:
            return
        if self.refresh_token:
            await self.refresh_session()
            return
        await self.login()

    @staticmethod
    def _is_api_error(payload: dict[str, Any]) -> bool:
        if payload.get("success") is False:
            return True
        if payload.get("status") is False:
            return True
        return False

    @staticmethod
    def _is_token_error(message: str | None) -> bool:
        if not message:
            return False
        lowered = message.lower()
        return "token" in lowered or "session" in lowered or "unauthorized" in lowered

    async def _recover_session(self, attempt: int) -> None:
        logger.warning(
            "Angel One session recovery attempt=%s client_code=%s",
            attempt,
            self.client_code,
        )
        if attempt == 0 and self.refresh_token:
            try:
                await self.refresh_session()
            except AngelOneAuthError as exc:
                logger.warning(
                    "Angel One refresh failed for client_code=%s, falling back to login: %s",
                    self.client_code,
                    exc,
                )
                await self.login()
        else:
            await self.login()
        smart = self._ensure_smart_connect()
        smart.setAccessToken(self.jwt_token)
        smart.setRefreshToken(self.refresh_token)

    async def _execute_with_session_recovery(
        self,
        sync_fn,
        *,
        retries: int = 2,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            await self.ensure_session()
            loop = asyncio.get_running_loop()
            try:
                result = await loop.run_in_executor(None, sync_fn)
                if isinstance(result, dict) and self._is_api_error(result):
                    message = result.get("message", "Angel One API error")
                    if self._is_token_error(message) and attempt < retries:
                        await self._recover_session(attempt)
                        continue
                    raise AngelOneAPIError(message, payload=result)
                return result if isinstance(result, dict) else {"status": True, "data": result}
            except AngelOneAuthError as exc:
                last_error = exc
                if attempt < retries:
                    await self._recover_session(attempt + 1)
                    continue
                raise
            except AngelOneAPIError as exc:
                last_error = exc
                if self._is_token_error(str(exc)) and attempt < retries:
                    await self._recover_session(attempt)
                    continue
                raise
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise AngelOneAPIError(str(exc)) from exc
        raise last_error or AngelOneAPIError("Unknown Angel One request failure")

    async def _request(
        self,
        method: str,
        route_key: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        authenticated: bool = True,
        retries: int = 2,
    ) -> dict[str, Any]:
        await self.ensure_session()
        url = f"{ROOT_URL}{ROUTES[route_key]}"
        headers = self._base_headers(authenticated=authenticated)

        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    if method.upper() == "GET":
                        response = await client.get(url, headers=headers, params=params)
                    else:
                        response = await client.post(url, headers=headers, json=json_body or params)

                payload = response.json() if response.content else {}
                if response.status_code >= 400:
                    raise AngelOneAPIError(
                        payload.get("message", f"HTTP {response.status_code}"),
                        status_code=response.status_code,
                        payload=payload,
                    )
                if isinstance(payload, dict) and self._is_api_error(payload):
                    message = payload.get("message", "Angel One API error")
                    if self._is_token_error(message) and attempt < retries:
                        await self._recover_session(attempt)
                        headers = self._base_headers(authenticated=authenticated)
                        continue
                    raise AngelOneAPIError(message, payload=payload)
                return payload
            except (httpx.HTTPError, AngelOneAPIError) as exc:
                last_error = exc
                if attempt < retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise
        raise last_error or AngelOneAPIError("Unknown request failure")

    async def get_profile(self) -> dict[str, Any]:
        return await self._request("GET", "profile")

    async def get_rms_limits(self) -> dict[str, Any]:
        await self.ensure_session()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self._rms_sync)
        if isinstance(result, dict) and self._is_api_error(result):
            raise AngelOneAPIError(
                result.get("message", "RMS fetch failed"),
                payload=result,
            )
        return result if isinstance(result, dict) else {"status": True, "data": result}

    def _rms_sync(self) -> dict[str, Any]:
        smart = self._ensure_smart_connect()
        if not getattr(smart, "access_token", None):
            raise AngelOneAPIError("Missing Angel One access token for RMS request")
        return smart.rmsLimit()

    async def verify_session(self) -> dict[str, Any]:
        """Validate the current JWT against Angel One RMS."""
        return await self.get_rms_limits()

    async def get_order_book(self) -> dict[str, Any]:
        return await self._request("GET", "order_book")

    async def get_trade_book(self) -> dict[str, Any]:
        return await self._request("GET", "trade_book")

    async def get_positions(self) -> dict[str, Any]:
        return await self._request("GET", "position")

    async def get_holdings(self) -> dict[str, Any]:
        return await self._request("GET", "holding")

    async def get_ltp(self, request: LTPRequest) -> dict[str, Any]:
        return await self._request("POST", "ltp", json_body=request.model_dump())

    async def get_candles(self, request: CandleRequest) -> dict[str, Any]:
        return await self._request("POST", "candles", json_body=request.model_dump())

    async def search_scrip(self, request: SearchScripRequest) -> dict[str, Any]:
        return await self._request("POST", "search_scrip", json_body=request.model_dump())

    async def place_order(self, request: PlaceOrderRequest) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._place_order_sync, request)

    def _place_order_sync(self, request: PlaceOrderRequest) -> dict[str, Any]:
        smart = self._ensure_smart_connect()
        order_params = request.model_dump(exclude_none=True)
        response = smart.placeOrderFullResponse(order_params)
        if not response or not response.get("status"):
            raise AngelOneAPIError(response.get("message", "Order placement failed"), payload=response or {})
        return response

    async def modify_order(self, request: ModifyOrderRequest) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._modify_order_sync, request)

    def _modify_order_sync(self, request: ModifyOrderRequest) -> dict[str, Any]:
        smart = self._ensure_smart_connect()
        response = smart.modifyOrder(request.model_dump(exclude_none=True))
        if isinstance(response, dict) and response.get("status") is False:
            raise AngelOneAPIError(response.get("message", "Order modify failed"), payload=response)
        return response if isinstance(response, dict) else {"status": True, "data": {"orderid": response}}

    async def cancel_order(self, request: CancelOrderRequest) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._cancel_order_sync, request)

    def _cancel_order_sync(self, request: CancelOrderRequest) -> dict[str, Any]:
        from trading_shared.broker.angel_one.orders import normalize_cancel_variety

        smart = self._ensure_smart_connect()
        variety = normalize_cancel_variety(request.variety)
        response = smart.cancelOrder(request.orderid, variety)
        if isinstance(response, dict) and response.get("status") is False:
            raise AngelOneAPIError(response.get("message", "Order cancel failed"), payload=response)
        return response if isinstance(response, dict) else {"status": True, "data": {"orderid": response}}

    async def logout(self) -> dict[str, Any]:
        if not self.client_code:
            return {"status": True, "message": "No active session"}
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._logout_sync)

    def _logout_sync(self) -> dict[str, Any]:
        smart = self._ensure_smart_connect()
        result = smart.terminateSession(self.client_code)
        self.jwt_token = None
        self.refresh_token = None
        self.feed_token = None
        self._session_expires_at = None
        return result if isinstance(result, dict) else {"status": True}

    def get_session_state(self) -> dict[str, Any]:
        return {
            "connected": bool(self.jwt_token),
            "client_code": self.client_code,
            "has_refresh_token": bool(self.refresh_token),
            "has_feed_token": bool(self.feed_token),
            "expires_at": self._session_expires_at.isoformat() if self._session_expires_at else None,
        }

    def restore_session(
        self,
        jwt_token: str,
        refresh_token: str,
        client_code: str,
        feed_token: str | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        self.jwt_token = self._normalize_bearer_token(jwt_token)
        self.refresh_token = refresh_token
        self.client_code = client_code
        self.feed_token = feed_token
        self._session_expires_at = expires_at
        self.reset_smart_connect()
        self._ensure_smart_connect()

    def to_cache_blob(self) -> str:
        payload = {
            "jwt_token": self.jwt_token,
            "refresh_token": self.refresh_token,
            "feed_token": self.feed_token,
            "client_code": self.client_code,
            "expires_at": self._session_expires_at.isoformat() if self._session_expires_at else None,
        }
        return json.dumps(payload)

    @classmethod
    def from_cache_blob(cls, api_key: str, blob: str, **kwargs: Any) -> "AngelOneClient":
        payload = json.loads(blob)
        client = cls(api_key=api_key, **kwargs)
        expires_at = None
        if payload.get("expires_at"):
            expires_at = datetime.fromisoformat(payload["expires_at"])
        client.restore_session(
            jwt_token=payload["jwt_token"],
            refresh_token=payload["refresh_token"],
            client_code=payload["client_code"],
            feed_token=payload.get("feed_token"),
            expires_at=expires_at,
        )
        return client
