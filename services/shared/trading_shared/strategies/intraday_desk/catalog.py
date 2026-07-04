"""Intraday desk strategy catalog — three modular, toggleable strategies."""

from __future__ import annotations

from typing import Any

_CATALOG_VERSION = 2

STRATEGY_CATALOG: list[dict[str, Any]] = [
    {
        "code": "INTRA-ORB",
        "id": "orb",
        "label": "Opening Range Breakout",
        "description": "Long-only first-bar ORB (9:45–11:30) · 1.5× volume · midpoint stop · 2R target · backtest-ranked universe.",
        "family": "intraday",
    },
    {
        "code": "INTRA-VWAP",
        "id": "vwap_trend",
        "label": "VWAP Trend",
        "description": "VWAP cross with 9-EMA alignment · 9:50–14:30 entry window · 1% trail · VWAP re-cross exit · performance-ranked picks.",
        "family": "intraday",
    },
    {
        "code": "INTRA-EMA-RSI",
        "id": "ema_rsi",
        "label": "EMA Crossover + RSI Filter",
        "description": "9/21 EMA cross 10:00–14:30 · RSI momentum · 2.5R target · only stocks with positive 60d backtest preview.",
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
