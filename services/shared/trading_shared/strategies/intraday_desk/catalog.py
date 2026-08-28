"""Intraday desk strategy catalog — modular, toggleable strategies."""

from __future__ import annotations

from typing import Any

_CATALOG_VERSION = 4

STRATEGY_CATALOG: list[dict[str, Any]] = [
    {
        "code": "INTRA-ORB",
        "id": "orb",
        "label": "Opening Range Breakout",
        "description": "Long-only ORB · OR→09:55 · entry 09:55–10:30 · EMA34 trend filter · 0.15% buffer · body≥60% · 0.20% stop · 3R.",
        "family": "intraday",
    },
    {
        "code": "INTRA-VWAP-ORB",
        "id": "vwap_orb",
        "label": "VWAP ORB Trend Filter",
        "description": "VWAP + OR (09:15–09:30) · EMA5/13 · vol≥1.35×SMA8 · ATR1.5 stop · BE@1.5ATR · scale@1R then EMA trail · entry 09:30–14:00 · 1 trade/day · chop after 1 stop.",
        "family": "intraday",
    },
]

INTRADAY_STRATEGIES = list(STRATEGY_CATALOG)

_CODE_INDEX: dict[str, dict[str, Any]] = {row["code"]: row for row in STRATEGY_CATALOG}
_ID_INDEX: dict[str, dict[str, Any]] = {row["id"]: row for row in STRATEGY_CATALOG}


def catalog_entry(strategy_code: str | None) -> dict[str, Any] | None:
    if not strategy_code:
        return None
    return _CODE_INDEX.get(strategy_code)


def strategy_id_for_code(strategy_code: str | None) -> str | None:
    entry = catalog_entry(strategy_code)
    return entry["id"] if entry else None


def default_strategy_settings() -> dict[str, dict[str, bool]]:
    return {row["code"]: {"enabled": True} for row in STRATEGY_CATALOG}


def merge_strategy_settings(config: dict | None) -> dict[str, dict[str, bool]]:
    merged = default_strategy_settings()
    raw = (config or {}).get("intraday_strategy_settings") or {}
    for code, settings in raw.items():
        if code in merged and isinstance(settings, dict):
            merged[code] = {**merged[code], **settings}
    return merged


def enabled_strategy_codes(config: dict | None = None) -> list[str]:
    settings = merge_strategy_settings(config)
    return [code for code, s in settings.items() if s.get("enabled", True)]
