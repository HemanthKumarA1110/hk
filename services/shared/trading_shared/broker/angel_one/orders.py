"""Angel One order helpers."""

from __future__ import annotations

CANCEL_VARIETIES = frozenset({"NORMAL", "STOPLOSS", "ROBO"})


def normalize_cancel_variety(variety: str | None) -> str:
    """Map order-book variety to values accepted by Angel One cancelOrder API."""
    value = (variety or "NORMAL").upper().strip()
    if value in CANCEL_VARIETIES:
        return value
    if "ROBO" in value:
        return "ROBO"
    if "STOP" in value:
        return "STOPLOSS"
    # AMO and other placement varieties cancel as NORMAL
    return "NORMAL"
