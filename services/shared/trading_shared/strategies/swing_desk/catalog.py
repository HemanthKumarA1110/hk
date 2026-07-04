"""Swing desk strategy catalog — three modular long-only strategies."""

from __future__ import annotations

from typing import Any

STRATEGY_CATALOG: list[dict[str, Any]] = [
    {
        "code": "SWING-EMA",
        "id": "ema_trend",
        "label": "EMA Crossover Trend-Following",
        "description": "20/50 EMA cross above 200 EMA · volume confirm · 10-day swing stop · 6% trail · 2.5R target · ranked universe.",
        "family": "swing",
    },
    {
        "code": "SWING-RSI",
        "id": "rsi_mean_reversion",
        "label": "RSI Mean-Reversion + 200 EMA Filter",
        "description": "RSI dip < 35 turning up above 200 EMA · 4.5% max stop · exit RSI > 58 or 2.2R · 15-day max hold.",
        "family": "swing",
    },
    {
        "code": "SWING-BO-ATR",
        "id": "breakout_atr",
        "label": "20-Day Breakout + ATR Chandelier",
        "description": "20-day high breakout above 200 EMA · 1.25× volume · 2× ATR stop · 2.5× ATR chandelier · ranked picks.",
        "family": "swing",
    },
]

SWING_STRATEGIES = list(STRATEGY_CATALOG)

_CODE_INDEX: dict[str, dict[str, Any]] = {row["code"]: row for row in STRATEGY_CATALOG}


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
    raw = (config or {}).get("swing_strategy_settings") or {}
    for code, settings in raw.items():
        if code in merged and isinstance(settings, dict):
            merged[code] = {**merged[code], **settings}
    return merged


def enabled_strategy_codes(config: dict | None = None) -> list[str]:
    settings = merge_strategy_settings(config)
    return [code for code, s in settings.items() if s.get("enabled", True)]
