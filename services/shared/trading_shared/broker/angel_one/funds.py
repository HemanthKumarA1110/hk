"""Parse Angel One RMS / funds API payloads."""

from __future__ import annotations

from typing import Any


def parse_rms_funds(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize Angel One RMS response for the dashboard."""
    data = raw.get("data")
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        data = {}

    available = _first_numeric(
        data,
        "availablecash",
        "availableCash",
        "availablemargin",
        "availableMargin",
        "availablelimitmargin",
        "availableLimitMargin",
        "net",
        "netAvailable",
    )

    normalized = dict(data)
    if available is not None:
        normalized["availablecash"] = available

    return {
        "status": _api_success(raw),
        "message": raw.get("message"),
        "data": normalized,
    }


def _api_success(raw: dict[str, Any]) -> bool:
    if "success" in raw:
        return bool(raw["success"])
    if "status" in raw:
        return bool(raw["status"])
    return True


def _first_numeric(data: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = data.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None
