"""Tests for Angel One credential persistence and reuse."""

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

# smartapi-python is optional in the local test env; stub before importing client code.
if "SmartApi" not in sys.modules:
    smart_api = ModuleType("SmartApi")
    smart_api.SmartConnect = MagicMock()
    sys.modules["SmartApi"] = smart_api

from trading_shared.broker.angel_one.session_manager import AngelOneSessionManager
from trading_shared.schemas.broker import BrokerCredentialRequest
from trading_shared.security.encryption import encrypt_value


ENCRYPTION_KEY = "phase1_dev_encryption_key_32chars"


def _fake_user(user_id: int = 7):
    user = MagicMock()
    user.id = user_id
    return user


def _cred_row(
    *,
    api_key="abcdefgh",
    client_code="A12345",
    password="secret",
    totp_secret="ABCDEFGHIJKLMNOP",
):
    row = MagicMock()
    row.user_id = 7
    row.broker_name = "angel_one"
    row.is_active = True
    row.encrypted_api_key = encrypt_value(api_key, ENCRYPTION_KEY)
    row.encrypted_client_code = encrypt_value(client_code, ENCRYPTION_KEY)
    row.encrypted_password = encrypt_value(password, ENCRYPTION_KEY)
    row.encrypted_totp_secret = encrypt_value(totp_secret, ENCRYPTION_KEY)
    return row


@pytest.fixture
def manager(monkeypatch):
    db = MagicMock()
    redis_client = MagicMock()
    redis_client.exists.return_value = 0
    mgr = AngelOneSessionManager(db, redis_client)
    monkeypatch.setattr(mgr.settings, "ENCRYPTION_KEY", ENCRYPTION_KEY)
    return mgr


def test_broker_credential_request_allows_partial_update():
    payload = BrokerCredentialRequest(password="new-pass")
    assert payload.password == "new-pass"
    assert payload.api_key is None
    assert payload.client_code is None
    assert payload.totp_secret is None


def test_broker_credential_request_rejects_all_blank():
    with pytest.raises(ValidationError):
        BrokerCredentialRequest()
    with pytest.raises(ValidationError):
        BrokerCredentialRequest(api_key="", client_code="", password="", totp_secret="")


def test_first_time_save_requires_all_fields(manager):
    manager.get_broker_credential = MagicMock(return_value=None)
    with pytest.raises(ValueError, match="First-time Angel One setup requires"):
        manager.save_broker_credential(
            user=_fake_user(),
            api_key="abcdefgh",
            client_code="A12345",
            password=None,
            totp_secret="ABCDEFGHIJKLMNOP",
        )


def test_partial_update_keeps_unspecified_secrets(manager):
    existing = _cred_row()
    manager.get_broker_credential = MagicMock(return_value=existing)

    manager.save_broker_credential(
        user=_fake_user(),
        api_key=None,
        client_code=None,
        password="new-password",
        totp_secret=None,
    )

    decrypted = manager._decrypt_credentials(existing)
    assert decrypted["api_key"] == "abcdefgh"
    assert decrypted["client_code"] == "A12345"
    assert decrypted["password"] == "new-password"
    assert decrypted["totp_secret"] == "ABCDEFGHIJKLMNOP"
    manager.db.commit.assert_called()


def test_status_exposes_client_code_from_saved_credentials(manager):
    existing = _cred_row(client_code="CLI999")
    manager.get_broker_credential = MagicMock(return_value=existing)
    manager.db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    status = manager.get_connection_status(7)

    assert status["credentials_configured"] is True
    assert status["connected"] is False
    assert status["client_code"] == "CLI999"


def test_connect_user_reuses_stored_credentials_without_resupply(manager):
    import asyncio

    existing = _cred_row(client_code="REUSE1")
    manager.get_broker_credential = MagicMock(return_value=existing)

    login_result = {
        "client_code": "REUSE1",
        "jwt_token": "jwt",
        "refresh_token": "rt",
        "feed_token": "ft",
        "expires_at": None,
    }
    client = MagicMock()

    async def _login():
        return login_result

    async def _verify():
        return None

    client.login = _login
    client.verify_session = _verify
    manager._build_client = MagicMock(return_value=client)
    manager.persist_client_session = MagicMock()
    manager.redis.delete = MagicMock()
    manager.redis.get = MagicMock(return_value=None)

    result = asyncio.run(manager.connect_user(7, force=True))

    assert result["connected"] is True
    assert result["client_code"] == "REUSE1"
    manager._build_client.assert_called_once()
    built_creds = manager._build_client.call_args[0][0]
    assert built_creds["api_key"] == "abcdefgh"
    assert built_creds["password"] == "secret"
    assert built_creds["totp_secret"] == "ABCDEFGHIJKLMNOP"
