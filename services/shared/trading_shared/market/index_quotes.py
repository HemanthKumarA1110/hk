"""Helpers for NIFTY / BANKNIFTY live quote payloads."""

from __future__ import annotations

from typing import Any


def quote_from_tick(name: str, meta: dict[str, str], tick: dict[str, Any], *, source: str) -> dict[str, Any]:
    ltp = _to_float(tick.get("ltp"))
    open_px = _to_float(tick.get("open")) or ltp
    close_px = _to_float(tick.get("close")) or open_px
    change = (ltp - close_px) if ltp is not None and close_px else None
    change_pct = (change / close_px * 100) if change is not None and close_px else None
    return {
        "name": name,
        "label": meta.get("tradingsymbol", name),
        "symboltoken": meta.get("symboltoken"),
        "exchange": meta.get("exchange"),
        "ltp": ltp,
        "open": open_px,
        "high": _to_float(tick.get("high")),
        "low": _to_float(tick.get("low")),
        "close": close_px,
        "change": round(change, 2) if change is not None else None,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "source": source,
    }


def extract_ltp_from_response(payload: dict[str, Any], symboltoken: str | None = None) -> float | None:
    """Parse Angel One LTP API payload (flat or token-keyed shapes)."""
    if payload.get("status") is False or payload.get("success") is False:
        return None

    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return None

    if data.get("ltp") is not None:
        return _to_float(data.get("ltp"))

    if symboltoken:
        row = data.get(str(symboltoken))
        if isinstance(row, dict) and row.get("ltp") is not None:
            return _to_float(row.get("ltp"))

    for value in data.values():
        if isinstance(value, dict) and value.get("ltp") is not None:
            parsed = _to_float(value.get("ltp"))
            if parsed is not None:
                return parsed
    return None


def parse_ltp_payload(name: str, meta: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") is False or payload.get("success") is False:
        return {
            "name": name,
            "label": meta.get("tradingsymbol", name),
            "symboltoken": meta.get("symboltoken"),
            "exchange": meta.get("exchange"),
            "ltp": None,
            "source": "broker_api",
            "error": payload.get("message") or "LTP unavailable",
        }

    data = payload.get("data") or {}
    row: dict[str, Any] | None = None

    if isinstance(data, dict):
        if data.get("ltp") is not None or data.get("symboltoken"):
            row = data
        else:
            row = data.get(str(meta.get("symboltoken", "")))
            if row is None:
                for value in data.values():
                    if isinstance(value, dict) and value.get("ltp") is not None:
                        row = value
                        break

    ltp = extract_ltp_from_response(payload, meta.get("symboltoken"))
    if ltp is None:
        message = payload.get("message") or "LTP unavailable"
        if str(message).upper() == "SUCCESS":
            message = "LTP unavailable"
        return {
            "name": name,
            "label": meta.get("tradingsymbol", name),
            "symboltoken": meta.get("symboltoken"),
            "exchange": meta.get("exchange"),
            "ltp": None,
            "source": "broker_api",
            "error": message,
        }

    tick = {
        "ltp": ltp,
        "open": row.get("open") if row else None,
        "high": row.get("high") if row else None,
        "low": row.get("low") if row else None,
        "close": row.get("close") if row else None,
    }
    quote = quote_from_tick(name, meta, tick, source="broker_api")
    quote["error"] = None
    return quote


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
