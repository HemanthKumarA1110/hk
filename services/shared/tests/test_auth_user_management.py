"""Focused tests for admin user create / password change / reset."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from trading_shared.models import User, UserRole
from trading_shared.schemas.auth import (
    AdminCreateUserRequest,
    AdminResetPasswordRequest,
    AdminUpdateUserRequest,
    ChangePasswordRequest,
    UserRoleEnum,
)
from trading_shared.security.password import hash_password, verify_password


def _load_auth_service():
    path = Path(__file__).resolve().parents[2] / "auth-service" / "app" / "services" / "auth_service.py"
    spec = importlib.util.spec_from_file_location("auth_service_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.AuthService


AuthService = _load_auth_service()


def _query_chain(result):
    chain = MagicMock()
    chain.filter.return_value = chain
    chain.first.return_value = result
    return chain


def test_admin_create_user_hashes_password_and_allows_trader_role():
    db = MagicMock()
    db.query.return_value = _query_chain(None)
    service = AuthService(db)
    service.settings = MagicMock(ENV="production", ALLOW_PUBLIC_REGISTRATION=False)
    service.record_audit = MagicMock()

    actor = User(id=1, username="admin", email="a@x.com", role=UserRole.ADMIN, is_active=True)
    payload = AdminCreateUserRequest(
        username="trader1",
        email="trader1@example.com",
        password="TraderPass1!",
        role=UserRoleEnum.TRADER,
    )

    def _add(obj):
        obj.id = 99

    db.add.side_effect = _add
    db.refresh.side_effect = lambda u: None

    user = service.create_user_as_admin(payload, actor)

    assert user.username == "trader1"
    assert user.role == UserRole.TRADER
    assert verify_password("TraderPass1!", user.hashed_password)
    assert user.hashed_password != "TraderPass1!"
    service.record_audit.assert_called()
    db.commit.assert_called()


def test_change_password_rejects_wrong_current():
    db = MagicMock()
    service = AuthService(db)
    service.record_audit = MagicMock()
    user = User(
        id=2,
        username="u",
        email="u@x.com",
        hashed_password=hash_password("OldPass123!"),
        role=UserRole.TRADER,
        is_active=True,
    )
    with pytest.raises(HTTPException) as exc:
        service.change_password(
            user,
            ChangePasswordRequest(current_password="wrong", new_password="NewPass123!"),
        )
    assert exc.value.status_code == 400


def test_change_password_updates_hash():
    db = MagicMock()
    service = AuthService(db)
    service.record_audit = MagicMock()
    user = User(
        id=2,
        username="u",
        email="u@x.com",
        hashed_password=hash_password("OldPass123!"),
        role=UserRole.TRADER,
        is_active=True,
    )
    result = service.change_password(
        user,
        ChangePasswordRequest(current_password="OldPass123!", new_password="NewPass123!"),
    )
    assert result["status"] == "ok"
    assert verify_password("NewPass123!", user.hashed_password)
    assert not verify_password("OldPass123!", user.hashed_password)


def test_admin_reset_password():
    db = MagicMock()
    target = User(
        id=5,
        username="trader1",
        email="t@x.com",
        hashed_password=hash_password("OldPass123!"),
        role=UserRole.TRADER,
        is_active=True,
    )
    db.query.return_value = _query_chain(target)
    service = AuthService(db)
    service.record_audit = MagicMock()
    actor = User(id=1, username="admin", email="a@x.com", role=UserRole.ADMIN, is_active=True)

    result = service.admin_reset_password(
        5, AdminResetPasswordRequest(new_password="ResetPass99!"), actor
    )
    assert result["status"] == "ok"
    assert verify_password("ResetPass99!", target.hashed_password)


def test_admin_cannot_deactivate_self():
    db = MagicMock()
    actor = User(id=1, username="admin", email="a@x.com", role=UserRole.ADMIN, is_active=True)
    db.query.return_value = _query_chain(actor)
    service = AuthService(db)
    service.record_audit = MagicMock()

    with pytest.raises(HTTPException) as exc:
        service.update_user(1, AdminUpdateUserRequest(is_active=False), actor)
    assert exc.value.status_code == 400
    assert "deactivate" in exc.value.detail.lower()


def test_admin_can_deactivate_and_reactivate_other_user():
    db = MagicMock()
    target = User(
        id=5,
        username="trader1",
        email="t@x.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.TRADER,
        is_active=True,
    )
    db.query.return_value = _query_chain(target)
    service = AuthService(db)
    service.record_audit = MagicMock()
    actor = User(id=1, username="admin", email="a@x.com", role=UserRole.ADMIN, is_active=True)

    deactivated = service.update_user(5, AdminUpdateUserRequest(is_active=False), actor)
    assert deactivated.is_active is False

    reactivated = service.update_user(5, AdminUpdateUserRequest(is_active=True), actor)
    assert reactivated.is_active is True
    assert service.record_audit.call_count == 2


def test_login_rejects_deactivated_user_with_clear_message():
    db = MagicMock()
    inactive = User(
        id=5,
        username="trader1",
        email="t@x.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.TRADER,
        is_active=False,
    )
    db.query.return_value = _query_chain(inactive)
    service = AuthService(db)
    service.settings = MagicMock(ACCESS_TOKEN_EXPIRE_MINUTES=30)
    service.record_audit = MagicMock()

    with pytest.raises(HTTPException) as exc:
        service.login("trader1", "Pass1234!")
    assert exc.value.status_code == 403
    assert "deactivated" in exc.value.detail.lower()


def test_login_still_returns_invalid_credentials_for_wrong_password():
    db = MagicMock()
    inactive = User(
        id=5,
        username="trader1",
        email="t@x.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.TRADER,
        is_active=False,
    )
    db.query.return_value = _query_chain(inactive)
    service = AuthService(db)

    with pytest.raises(HTTPException) as exc:
        service.login("trader1", "WrongPass!")
    assert exc.value.status_code == 401
    assert exc.value.detail == "Invalid credentials"


def test_admin_create_schemas_accept_roles():
    payload = AdminCreateUserRequest(
        username="ops",
        email="ops@example.com",
        password="OpsPass123!",
        role=UserRoleEnum.ADMIN,
    )
    assert payload.role == UserRoleEnum.ADMIN
