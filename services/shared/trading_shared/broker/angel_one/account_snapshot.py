"""Normalize Angel One orders, positions, holdings, and trades."""

from __future__ import annotations

from typing import Any

from trading_shared.broker.angel_one.orders import normalize_cancel_variety


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    return int(_float(value, default))


def is_cancellable_status(status: str | None) -> bool:
    value = (status or "").strip().lower()
    if not value:
        return False
    terminal = ("complete", "cancel", "reject", "filled", "expired", "invalid", "closed")
    return not any(term in value for term in terminal)


def normalize_orders(rows: list[dict] | None) -> list[dict]:
    result: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        status = row.get("status") or row.get("orderstatus") or row.get("text")
        result.append(
            {
                "order_id": str(row.get("orderid") or row.get("order_id") or ""),
                "symbol": row.get("tradingsymbol") or row.get("symbol"),
                "side": row.get("transactiontype") or row.get("side"),
                "qty": _int(row.get("quantity") or row.get("qty")),
                "filled_qty": _int(row.get("filledshares") or row.get("filledquantity")),
                "price": _float(row.get("price")),
                "trigger_price": _float(row.get("triggerprice")),
                "order_type": row.get("ordertype") or row.get("order_type"),
                "product": row.get("producttype") or row.get("product"),
                "variety": row.get("variety") or "NORMAL",
                "cancel_variety": normalize_cancel_variety(row.get("variety")),
                "status": status,
                "exchange": row.get("exchange"),
                "updated_at": row.get("updatetime") or row.get("exchtime") or row.get("ordertime"),
                "cancellable": is_cancellable_status(status),
            }
        )
    return result


def normalize_trades(rows: list[dict] | None) -> list[dict]:
    result: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        result.append(
            {
                "trade_id": str(row.get("fillid") or row.get("tradeid") or row.get("orderid") or ""),
                "order_id": str(row.get("orderid") or ""),
                "symbol": row.get("tradingsymbol") or row.get("symbol"),
                "side": row.get("transactiontype") or row.get("side"),
                "qty": _int(row.get("quantity") or row.get("fillsize") or row.get("qty")),
                "price": _float(row.get("price") or row.get("fillprice")),
                "exchange": row.get("exchange"),
                "product": row.get("producttype") or row.get("product"),
                "timestamp": row.get("filltime") or row.get("updatetime") or row.get("exchtime"),
            }
        )
    return result


def normalize_positions(rows: list[dict] | None) -> list[dict]:
    result: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        qty = _int(row.get("netqty") or row.get("quantity"))
        if qty == 0:
            qty = _int(row.get("buyqty")) - _int(row.get("sellqty"))
        if qty == 0:
            continue
        result.append(
            {
                "symbol": row.get("tradingsymbol") or row.get("symbol"),
                "qty": qty,
                "avg_price": _float(row.get("averageprice") or row.get("avgprice")),
                "ltp": _float(row.get("ltp")),
                "pnl": _float(row.get("pnl") or row.get("unrealised")),
                "product": row.get("producttype") or row.get("product"),
                "exchange": row.get("exchange"),
                "type": "position",
            }
        )
    return result


def normalize_holdings(rows: list[dict] | None) -> list[dict]:
    result: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        qty = _int(row.get("quantity") or row.get("qty"))
        if qty == 0:
            continue
        result.append(
            {
                "symbol": row.get("tradingsymbol") or row.get("symbol"),
                "qty": qty,
                "avg_price": _float(row.get("averageprice") or row.get("avgprice")),
                "ltp": _float(row.get("ltp")),
                "pnl": _float(row.get("profitandloss") or row.get("pnl")),
                "current_value": _float(row.get("currentvalue")),
                "exchange": row.get("exchange"),
                "type": "holding",
            }
        )
    return result
