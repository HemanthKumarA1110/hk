"""Tests for per-user page access helpers and admin updates."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from trading_shared.auth.pages import (
    ALL_PAGE_KEYS,
    DEFAULT_TRADER_PAGES,
    LEGACY_FULL_PAGES,
    normalize_allowed_pages,
    path_to_page_key,
    resolve_allowed_pages,
    serialize_allowed_pages,
    user_can_access_path,
)
from trading_shared.models import User, UserRole
from trading_shared.schemas.auth import AdminCreateUserRequest, AdminUpdateUserRequest, UserRoleEnum
from trading_shared.security.password import hash_password


def _load_auth_service():
    path = Path(__file__).resolve().parents[2] / "auth-service" / "app" / "services" / "auth_service.py"
    spec = importlib.util.spec_from_file_location("auth_service_pages_under_test", path)
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


def test_admin_always_resolves_to_all_pages():
    assert resolve_allowed_pages(UserRole.ADMIN, None) == ALL_PAGE_KEYS
    assert resolve_allowed_pages(UserRole.ADMIN, json.dumps(["overview"])) == ALL_PAGE_KEYS
    assert "admin_users" in resolve_allowed_pages(UserRole.ADMIN, None)


def test_legacy_null_pages_keep_full_non_admin_access():
    pages = resolve_allowed_pages(UserRole.TRADER, None)
    assert pages == LEGACY_FULL_PAGES
    assert "admin_users" not in pages
    assert "overview" in pages


def test_normalize_strips_admin_pages_for_traders():
    pages = normalize_allowed_pages(
        ["overview", "admin_users", "unknown", "live", "account"],
        role=UserRole.TRADER,
    )
    assert "admin_users" not in pages
    assert "unknown" not in pages
    assert pages == ["overview", "live", "account"]


def test_normalize_always_keeps_account():
    pages = normalize_allowed_pages(["overview", "live"], role="viewer")
    assert "account" in pages


def test_path_matching_prefers_specific_routes():
    assert path_to_page_key("/") == "overview"
    assert path_to_page_key("/scalping/nifty50") == "scalping_nifty"
    assert path_to_page_key("/scalping/banknifty") == "scalping_banknifty"
    assert path_to_page_key("/scalping") is None
    assert path_to_page_key("/backtest/results") == "backtest_results"
    assert path_to_page_key("/swing/ideas") == "swing_ideas"
    assert path_to_page_key("/swing") == "swing"
    assert path_to_page_key("/intraday/ideas") == "intraday_ideas"
    assert path_to_page_key("/intraday") == "intraday"
    assert path_to_page_key("/orders") == "orders"
    assert path_to_page_key("/admin/users") == "admin_users"


def test_user_can_access_path_respects_allowed_list():
    raw = serialize_allowed_pages(["overview", "account"])
    assert user_can_access_path(UserRole.TRADER, raw, "/")
    assert user_can_access_path(UserRole.TRADER, raw, "/account")
    assert not user_can_access_path(UserRole.TRADER, raw, "/live")
    assert user_can_access_path(UserRole.ADMIN, raw, "/admin/users")


def test_admin_create_user_stores_default_trader_pages():
    db = MagicMock()
    db.query.return_value = _query_chain(None)
    service = AuthService(db)
    service.settings = MagicMock(ENV="production", ALLOW_PUBLIC_REGISTRATION=False)
    service.record_audit = MagicMock()
    actor = User(id=1, username="admin", email="a@x.com", role=UserRole.ADMIN, is_active=True)

    def _add(obj):
        obj.id = 42

    db.add.side_effect = _add
    db.refresh.side_effect = lambda u: None

    user = service.create_user_as_admin(
        AdminCreateUserRequest(
            username="trader2",
            email="trader2@example.com",
            password="TraderPass1!",
            role=UserRoleEnum.TRADER,
        ),
        actor,
    )
    assert json.loads(user.allowed_pages_json) == DEFAULT_TRADER_PAGES
    assert user.allowed_pages == DEFAULT_TRADER_PAGES


def test_admin_create_user_respects_custom_pages():
    db = MagicMock()
    db.query.return_value = _query_chain(None)
    service = AuthService(db)
    service.record_audit = MagicMock()
    actor = User(id=1, username="admin", email="a@x.com", role=UserRole.ADMIN, is_active=True)
    db.add.side_effect = lambda obj: setattr(obj, "id", 7)
    db.refresh.side_effect = lambda u: None

    user = service.create_user_as_admin(
        AdminCreateUserRequest(
            username="limited",
            email="limited@example.com",
            password="TraderPass1!",
            role=UserRoleEnum.VIEWER,
            allowed_pages=["overview", "journal", "admin_users"],
        ),
        actor,
    )
    stored = json.loads(user.allowed_pages_json)
    assert stored == ["overview", "journal", "account"]
    assert "admin_users" not in stored


def test_admin_update_allowed_pages():
    db = MagicMock()
    target = User(
        id=5,
        username="trader1",
        email="t@x.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.TRADER,
        is_active=True,
        allowed_pages_json=serialize_allowed_pages(DEFAULT_TRADER_PAGES),
    )
    db.query.return_value = _query_chain(target)
    service = AuthService(db)
    service.record_audit = MagicMock()
    actor = User(id=1, username="admin", email="a@x.com", role=UserRole.ADMIN, is_active=True)

    updated = service.update_user(
        5,
        AdminUpdateUserRequest(allowed_pages=["overview", "live"]),
        actor,
    )
    assert json.loads(updated.allowed_pages_json) == ["overview", "live", "account"]
    assert updated.allowed_pages == ["overview", "live", "account"]


def test_promoting_to_admin_grants_all_pages():
    db = MagicMock()
    target = User(
        id=5,
        username="trader1",
        email="t@x.com",
        hashed_password=hash_password("Pass1234!"),
        role=UserRole.TRADER,
        is_active=True,
        allowed_pages_json=serialize_allowed_pages(["overview", "account"]),
    )
    db.query.return_value = _query_chain(target)
    service = AuthService(db)
    service.record_audit = MagicMock()
    actor = User(id=1, username="admin", email="a@x.com", role=UserRole.ADMIN, is_active=True)

    updated = service.update_user(5, AdminUpdateUserRequest(role=UserRoleEnum.ADMIN), actor)
    assert updated.role == UserRole.ADMIN
    assert updated.allowed_pages == ALL_PAGE_KEYS
    assert "admin_users" in json.loads(updated.allowed_pages_json)


def test_user_response_property_exposes_allowed_pages():
    user = User(
        id=3,
        username="u",
        email="u@x.com",
        hashed_password="x",
        role=UserRole.TRADER,
        is_active=True,
        allowed_pages_json=serialize_allowed_pages(["overview", "account"]),
    )
    assert user.allowed_pages == ["overview", "account"]
