"""Stable strategy codes for intraday and swing backtesting."""

from __future__ import annotations

from typing import Any

from trading_shared.strategies.intraday_desk.catalog import (
    INTRADAY_STRATEGIES,
    strategy_id_for_code as intraday_strategy_id,
)
from trading_shared.strategies.swing_desk.catalog import (
    SWING_STRATEGIES,
    strategy_id_for_code as swing_strategy_id,
)

_CATALOG_VERSION = 4

_CODE_INDEX: dict[str, dict[str, Any]] = {
    row["code"]: row for row in INTRADAY_STRATEGIES + SWING_STRATEGIES
}


def catalog_for_engine(engine: str) -> list[dict[str, Any]]:
    if engine == "intraday":
        return list(INTRADAY_STRATEGIES)
    if engine == "swing":
        return list(SWING_STRATEGIES)
    return []


def resolve_strategy_code(strategy_code: str | None) -> dict[str, Any] | None:
    if not strategy_code:
        return None
    return _CODE_INDEX.get(strategy_code)


def confirmation_filter_for_code(strategy_code: str | None) -> str | None:
    """Returns strategy id for intraday/swing modular desks."""
    entry = resolve_strategy_code(strategy_code)
    if not entry:
        return None
    return entry.get("id")


def strategy_id_for_code(strategy_code: str | None) -> str | None:
    entry = resolve_strategy_code(strategy_code)
    if not entry:
        return intraday_strategy_id(strategy_code) or swing_strategy_id(strategy_code)
    return entry.get("id")
