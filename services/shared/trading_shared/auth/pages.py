"""Controllable app pages for per-user access."""

from __future__ import annotations

import json
from typing import Iterable

from trading_shared.models.user import UserRole

# Stable page keys used in DB + API + frontend.
PAGE_CATALOG: list[dict[str, str]] = [
    {"key": "overview", "path": "/", "label": "Overview"},
    {"key": "scalping_nifty", "path": "/scalping/nifty50", "label": "Nifty Scalping"},
    {"key": "scalping_banknifty", "path": "/scalping/banknifty", "label": "Bank Nifty Scalping"},
    {"key": "intraday", "path": "/intraday", "label": "Intraday"},
    {"key": "swing", "path": "/swing", "label": "Swing"},
    {"key": "swing_ideas", "path": "/swing/ideas", "label": "Swing Ideas"},
    {"key": "portfolio", "path": "/portfolio", "label": "Portfolio"},
    {"key": "live", "path": "/live", "label": "Live Trading"},
    {"key": "orders", "path": "/orders", "label": "Orders & Positions"},
    {"key": "strategy", "path": "/strategy", "label": "Strategy"},
    {"key": "backtest", "path": "/backtest", "label": "Backtesting"},
    {"key": "backtest_results", "path": "/backtest/results", "label": "Backtest Results"},
    {"key": "journal", "path": "/journal", "label": "Journal"},
    {"key": "alerts", "path": "/alerts", "label": "Alerts"},
    {"key": "ai", "path": "/ai", "label": "AI Monitor"},
    {"key": "notepad", "path": "/notepad", "label": "Notepad"},
    {"key": "account", "path": "/account", "label": "Account"},
    {"key": "admin_users", "path": "/admin/users", "label": "Users Admin"},
]

ALL_PAGE_KEYS: list[str] = [p["key"] for p in PAGE_CATALOG]
ALL_PAGE_KEY_SET = frozenset(ALL_PAGE_KEYS)
ADMIN_ONLY_PAGES = frozenset({"admin_users"})

# New traders/viewers: common trading workspace + account.
DEFAULT_TRADER_PAGES: list[str] = [
    "overview",
    "scalping_nifty",
    "scalping_banknifty",
    "intraday",
    "swing",
    "swing_ideas",
    "live",
    "orders",
    "strategy",
    "journal",
    "account",
]

# Legacy users with NULL allowed_pages keep broad access (minus admin).
LEGACY_FULL_PAGES: list[str] = [k for k in ALL_PAGE_KEYS if k not in ADMIN_ONLY_PAGES]

# Prefer longer paths first when matching routes.
_PATH_TO_KEY = sorted(
    ((p["path"], p["key"]) for p in PAGE_CATALOG),
    key=lambda item: len(item[0]),
    reverse=True,
)


def default_pages_for_role(role: UserRole | str) -> list[str]:
    role_value = role.value if isinstance(role, UserRole) else str(role)
    if role_value == UserRole.ADMIN.value:
        return list(ALL_PAGE_KEYS)
    return list(DEFAULT_TRADER_PAGES)


def parse_allowed_pages_json(raw: str | None) -> list[str] | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, list):
        return None
    return [str(item) for item in data if isinstance(item, (str, int))]


def serialize_allowed_pages(pages: Iterable[str]) -> str:
    return json.dumps(list(pages))


def normalize_allowed_pages(
    pages: Iterable[str] | None,
    *,
    role: UserRole | str,
) -> list[str]:
    """Validate keys, drop unknown, and enforce role rules."""
    role_value = role.value if isinstance(role, UserRole) else str(role)
    if role_value == UserRole.ADMIN.value:
        return list(ALL_PAGE_KEYS)

    if pages is None:
        return list(DEFAULT_TRADER_PAGES)

    seen: set[str] = set()
    ordered: list[str] = []
    for key in pages:
        key_str = str(key).strip()
        if key_str not in ALL_PAGE_KEY_SET or key_str in ADMIN_ONLY_PAGES:
            continue
        if key_str in seen:
            continue
        seen.add(key_str)
        ordered.append(key_str)

    # Always keep Account so users can manage their login.
    if "account" not in seen:
        ordered.append("account")
    if not ordered:
        return list(DEFAULT_TRADER_PAGES)
    return ordered


def resolve_allowed_pages(role: UserRole | str, raw_json: str | None) -> list[str]:
    role_value = role.value if isinstance(role, UserRole) else str(role)
    if role_value == UserRole.ADMIN.value:
        return list(ALL_PAGE_KEYS)

    parsed = parse_allowed_pages_json(raw_json)
    if parsed is None:
        # Existing rows before this feature: keep previous full sidebar (no Users Admin).
        return list(LEGACY_FULL_PAGES)
    return normalize_allowed_pages(parsed, role=role_value)


def path_to_page_key(pathname: str) -> str | None:
    path = (pathname or "/").rstrip("/") or "/"
    for candidate, key in _PATH_TO_KEY:
        cand = candidate.rstrip("/") or "/"
        if path == cand or (cand != "/" and path.startswith(cand + "/")):
            return key
    return None


def user_can_access_path(role: UserRole | str, raw_json: str | None, pathname: str) -> bool:
    key = path_to_page_key(pathname)
    if key is None:
        return False
    return key in resolve_allowed_pages(role, raw_json)
