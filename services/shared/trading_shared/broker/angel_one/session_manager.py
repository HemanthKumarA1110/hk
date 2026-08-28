"""Redis-backed Angel One session manager for multi-service access."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import redis
from sqlalchemy.orm import Session

from trading_shared.broker.angel_one.client import AngelOneClient
from trading_shared.broker.angel_one.exceptions import AngelOneAPIError, AngelOneAuthError
from trading_shared.config import get_settings
from trading_shared.models import BrokerCredential, BrokerSession, User
from trading_shared.security.encryption import decrypt_value, encrypt_value

logger = logging.getLogger(__name__)


class AngelOneSessionManager:
    CACHE_PREFIX = "angel_one:session:"
    LOGIN_COOLDOWN_PREFIX = "angel_one:login_cooldown:"
    SESSION_STALE_PREFIX = "angel_one:session_stale:"
    LOGIN_COOLDOWN_SECONDS = 300

    def __init__(self, db: Session, redis_client: redis.Redis | None = None):
        self.db = db
        self.settings = get_settings()
        self.redis = redis_client or redis.from_url(self.settings.REDIS_URL, decode_responses=True)

    def _cache_key(self, user_id: int) -> str:
        return f"{self.CACHE_PREFIX}{user_id}"

    def _decrypt_credentials(self, cred: BrokerCredential) -> dict[str, str]:
        key = self.settings.ENCRYPTION_KEY
        return {
            "api_key": decrypt_value(cred.encrypted_api_key, key),
            "client_code": decrypt_value(cred.encrypted_client_code, key),
            "password": decrypt_value(cred.encrypted_password, key),
            "totp_secret": decrypt_value(cred.encrypted_totp_secret, key),
        }

    def _build_client(self, creds: dict[str, str]) -> AngelOneClient:
        return AngelOneClient(
            api_key=creds["api_key"],
            client_code=creds["client_code"],
            password=creds["password"],
            totp_secret=creds["totp_secret"],
            client_local_ip=self.settings.ANGEL_CLIENT_LOCAL_IP,
            client_public_ip=self.settings.ANGEL_CLIENT_PUBLIC_IP,
            mac_address=self.settings.ANGEL_MAC_ADDRESS,
        )

    def get_broker_credential(self, user_id: int) -> BrokerCredential | None:
        return (
            self.db.query(BrokerCredential)
            .filter(BrokerCredential.user_id == user_id, BrokerCredential.is_active.is_(True))
            .first()
        )

    def save_broker_credential(
        self,
        user: User,
        api_key: str | None = None,
        client_code: str | None = None,
        password: str | None = None,
        totp_secret: str | None = None,
    ) -> BrokerCredential:
        """Create or partially update encrypted Angel One credentials.

        Omitted / empty fields keep existing secrets. First-time setup requires
        all four fields.
        """
        key = self.settings.ENCRYPTION_KEY
        existing = self.get_broker_credential(user.id)

        if existing:
            current = self._decrypt_credentials(existing)
            merged_api_key = (api_key or "").strip() or current["api_key"]
            merged_client_code = (client_code or "").strip() or current["client_code"]
            merged_password = password if password not in (None, "") else current["password"]
            raw_totp = (totp_secret or "").replace(" ", "").strip().upper()
            merged_totp = raw_totp or current["totp_secret"]

            existing.encrypted_api_key = encrypt_value(merged_api_key, key)
            existing.encrypted_client_code = encrypt_value(merged_client_code, key)
            existing.encrypted_password = encrypt_value(merged_password, key)
            existing.encrypted_totp_secret = encrypt_value(merged_totp, key)
            existing.is_active = True
            cred = existing
        else:
            missing = [
                name
                for name, value in (
                    ("api_key", api_key),
                    ("client_code", client_code),
                    ("password", password),
                    ("totp_secret", totp_secret),
                )
                if not (value or "").strip()
            ]
            if missing:
                raise ValueError(
                    "First-time Angel One setup requires all fields: " + ", ".join(missing)
                )
            normalized_totp = (totp_secret or "").replace(" ", "").strip().upper()
            cred = BrokerCredential(
                user_id=user.id,
                broker_name="angel_one",
                encrypted_api_key=encrypt_value((api_key or "").strip(), key),
                encrypted_client_code=encrypt_value((client_code or "").strip(), key),
                encrypted_password=encrypt_value(password or "", key),
                encrypted_totp_secret=encrypt_value(normalized_totp, key),
            )
            self.db.add(cred)
        self.db.commit()
        self.db.refresh(cred)
        return cred

    async def connect_user(self, user_id: int, *, force: bool = False) -> dict:
        cooldown_key = f"{self.LOGIN_COOLDOWN_PREFIX}{user_id}"
        stale_key = f"{self.SESSION_STALE_PREFIX}{user_id}"
        if force:
            self.redis.delete(cooldown_key)
            self.redis.delete(stale_key)
        elif self.redis.get(cooldown_key):
            ttl = max(int(self.redis.ttl(cooldown_key) or 0), 60)
            raise AngelOneAuthError(
                f"Angel One login rate limited. Wait about {ttl} seconds, then reconnect manually."
            )

        cred = self.get_broker_credential(user_id)
        if not cred:
            raise AngelOneAuthError("Broker credentials not configured")

        creds = self._decrypt_credentials(cred)
        logger.info("Angel One connect starting for user_id=%s client_code=%s", user_id, creds["client_code"])
        client = self._build_client(creds)
        try:
            login_result = await client.login()
        except AngelOneAuthError as exc:
            message = str(exc).lower()
            if "rate" in message or "access denied" in message:
                self.redis.setex(cooldown_key, self.LOGIN_COOLDOWN_SECONDS, "1")
            logger.error("Angel One connect failed for user_id=%s: %s", user_id, exc)
            raise

        self.redis.delete(cooldown_key)
        self.redis.delete(stale_key)

        try:
            await client.verify_session()
        except AngelOneAPIError as exc:
            client.reset_smart_connect()
            message = str(exc).lower()
            if "rate" in message or "access denied" in message:
                self.redis.setex(cooldown_key, self.LOGIN_COOLDOWN_SECONDS, "1")
            self.mark_session_stale(user_id, str(exc))
            logger.error("Angel One session verification failed for user_id=%s: %s", user_id, exc)
            raise AngelOneAuthError(f"Login succeeded but session verification failed: {exc}") from exc

        logger.info(
            "Angel One connect succeeded for user_id=%s client_code=%s expires_at=%s",
            user_id,
            login_result.get("client_code"),
            login_result.get("expires_at"),
        )
        self.persist_client_session(user_id, client, login_result)
        return {
            "connected": True,
            "client_code": login_result["client_code"],
            "feed_token": login_result.get("feed_token"),
            "expires_at": login_result.get("expires_at"),
        }

    def _persist_session(self, user_id: int, client: AngelOneClient, login_result: dict) -> BrokerSession:
        self.db.query(BrokerSession).filter(
            BrokerSession.user_id == user_id,
            BrokerSession.broker_name == "angel_one",
        ).update({"is_active": False})

        expires_at = None
        if login_result.get("expires_at"):
            expires_at = datetime.fromisoformat(login_result["expires_at"])

        session = BrokerSession(
            user_id=user_id,
            broker_name="angel_one",
            jwt_token=login_result["jwt_token"],
            refresh_token=login_result["refresh_token"],
            feed_token=login_result.get("feed_token"),
            client_code=login_result["client_code"],
            expires_at=expires_at,
            is_active=True,
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    async def get_client_for_user(self, user_id: int) -> AngelOneClient:
        cred = self.get_broker_credential(user_id)
        if not cred:
            raise AngelOneAuthError("Broker credentials not configured")

        creds = self._decrypt_credentials(cred)
        cached = self.redis.get(self._cache_key(user_id))
        if cached:
            try:
                client = AngelOneClient.from_cache_blob(
                    api_key=creds["api_key"],
                    blob=cached,
                    client_code=creds["client_code"],
                    password=creds["password"],
                    totp_secret=creds["totp_secret"],
                    client_local_ip=self.settings.ANGEL_CLIENT_LOCAL_IP,
                    client_public_ip=self.settings.ANGEL_CLIENT_PUBLIC_IP,
                    mac_address=self.settings.ANGEL_MAC_ADDRESS,
                )
            except (json.JSONDecodeError, ValueError, KeyError) as exc:
                logger.warning("Invalid Angel One session cache for user_id=%s: %s", user_id, exc)
                self.redis.delete(self._cache_key(user_id))
            else:
                try:
                    await client.ensure_session()
                    self.persist_client_session(user_id, client)
                    self.clear_session_stale(user_id)
                    return client
                except AngelOneAuthError as exc:
                    logger.warning(
                        "Cached Angel One session invalid for user_id=%s, re-logging in: %s",
                        user_id,
                        exc,
                    )
                    self.redis.delete(self._cache_key(user_id))
                    self.mark_session_stale(user_id, str(exc))

        client = self._build_client(creds)
        logger.info("Angel One session login starting for user_id=%s client_code=%s", user_id, creds["client_code"])
        try:
            login_result = await client.login()
        except AngelOneAuthError as exc:
            friendly = AngelOneClient._friendly_auth_error(exc)
            logger.error("Angel One session login failed for user_id=%s: %s", user_id, friendly)
            raise AngelOneAuthError(friendly) from exc
        logger.info("Angel One session login succeeded for user_id=%s", user_id)
        self.clear_session_stale(user_id)
        self.persist_client_session(user_id, client, login_result)
        return client

    def persist_client_session(
        self,
        user_id: int,
        client: AngelOneClient,
        login_result: dict | None = None,
    ) -> None:
        if login_result:
            self._persist_session(user_id, client, login_result)
        else:
            self.db.query(BrokerSession).filter(
                BrokerSession.user_id == user_id,
                BrokerSession.broker_name == "angel_one",
                BrokerSession.is_active.is_(True),
            ).update(
                {
                    "jwt_token": client.jwt_token,
                    "refresh_token": client.refresh_token,
                    "feed_token": client.feed_token,
                    "expires_at": client._session_expires_at,
                }
            )
            self.db.commit()
        self.redis.setex(self._cache_key(user_id), 3600 * 8, client.to_cache_blob())
        system_blob = json.loads(client.to_cache_blob())
        system_blob["user_id"] = user_id
        cred = self.get_broker_credential(user_id)
        if cred:
            system_blob["api_key"] = self._decrypt_credentials(cred)["api_key"]
        elif self.settings.ANGEL_API_KEY:
            system_blob["api_key"] = self.settings.ANGEL_API_KEY
        self.redis.setex("angel_one:system:session", 3600 * 8, json.dumps(system_blob))

    def mark_session_stale(self, user_id: int, reason: str = "") -> None:
        key = f"{self.SESSION_STALE_PREFIX}{user_id}"
        self.redis.setex(key, 3600 * 8, reason or "invalid_token")

    def clear_session_stale(self, user_id: int) -> None:
        self.redis.delete(f"{self.SESSION_STALE_PREFIX}{user_id}")

    def is_session_stale(self, user_id: int) -> bool:
        return self.redis.exists(f"{self.SESSION_STALE_PREFIX}{user_id}") == 1

    async def disconnect_user(self, user_id: int) -> dict:
        try:
            client = await self.get_client_for_user(user_id)
            await client.logout()
        except AngelOneAuthError:
            pass
        self.redis.delete(self._cache_key(user_id))
        self.clear_session_stale(user_id)
        self.db.query(BrokerSession).filter(
            BrokerSession.user_id == user_id,
            BrokerSession.broker_name == "angel_one",
        ).update({"is_active": False})
        self.db.commit()
        return {"connected": False}

    def get_connection_status(self, user_id: int) -> dict:
        session = (
            self.db.query(BrokerSession)
            .filter(
                BrokerSession.user_id == user_id,
                BrokerSession.broker_name == "angel_one",
                BrokerSession.is_active.is_(True),
            )
            .order_by(BrokerSession.created_at.desc())
            .first()
        )
        cred = self.get_broker_credential(user_id)
        stale_key = f"{self.SESSION_STALE_PREFIX}{user_id}"
        needs_reconnect = self.redis.exists(stale_key) == 1
        has_session = session is not None and bool(session.jwt_token)
        client_code = session.client_code if session else None
        if not client_code and cred is not None:
            try:
                client_code = self._decrypt_credentials(cred)["client_code"]
            except ValueError:
                client_code = None
        return {
            "credentials_configured": cred is not None,
            "connected": has_session,
            "session_valid": has_session and not needs_reconnect,
            "needs_reconnect": needs_reconnect,
            "client_code": client_code,
            "feed_token_available": bool(session and session.feed_token),
            "expires_at": session.expires_at.isoformat() if session and session.expires_at else None,
            "cached_in_redis": self.redis.exists(self._cache_key(user_id)) == 1,
        }
