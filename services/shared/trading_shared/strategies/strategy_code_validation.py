"""Validate strategy codes belong to the correct trading desk (scalping / intraday / swing)."""

from __future__ import annotations

DESK_ENGINE_PREFIX: dict[str, str] = {
    "scalping": "SCALP-",
    "intraday": "INTRA-",
    "swing": "SWING-",
}


def desk_for_strategy_code(strategy_code: str | None) -> str | None:
    if not strategy_code:
        return None
    for desk, prefix in DESK_ENGINE_PREFIX.items():
        if strategy_code.startswith(prefix):
            return desk
    return None


def validate_strategy_code_for_engine(engine: str, strategy_code: str | None) -> str | None:
    """Raise ValueError if code does not belong to this desk/engine."""
    if not strategy_code:
        return None
    expected_prefix = DESK_ENGINE_PREFIX.get(engine)
    if not expected_prefix:
        raise ValueError(f"Unknown engine: {engine}")
    if not strategy_code.startswith(expected_prefix):
        desk = desk_for_strategy_code(strategy_code) or "unknown"
        raise ValueError(
            f"Strategy {strategy_code} belongs to {desk}, not {engine}. "
            f"Use the {desk} desk for that strategy."
        )
    return strategy_code


def filter_catalog_for_engine(engine: str, rows: list[dict]) -> list[dict]:
    """Keep only strategies whose code or family matches the desk."""
    prefix = DESK_ENGINE_PREFIX.get(engine, "")
    filtered = []
    for row in rows:
        code = str(row.get("code") or "")
        family = str(row.get("family") or row.get("desk") or "")
        if code.startswith(prefix) or family == engine:
            filtered.append(row)
    return filtered
