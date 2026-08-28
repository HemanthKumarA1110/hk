"""Lot-size helpers for broker quantity."""

from __future__ import annotations


def snap_qty_to_lot(qty: int, lot_size: int) -> int:
    """Round quantity down to a whole lot. Returns 0 if it cannot form one lot."""
    qty_i = int(qty or 0)
    lot = int(lot_size or 1)
    if qty_i <= 0:
        return 0
    if lot <= 1:
        return qty_i
    return (qty_i // lot) * lot


# Angel/NSE freeze for many index-option contracts (must stay a lot multiple).
# Exchange messages often say "maximum limit 601"; legal lot multiples stay at 600.
NFO_MAX_ORDER_QTY = 600


def max_lots_per_order(lot_size: int, max_qty: int = NFO_MAX_ORDER_QTY) -> int:
    """Max whole lots allowed in a single NFO order under the exchange freeze."""
    lot = max(int(lot_size or 1), 1)
    return max(1, int(max_qty) // lot)


def cap_qty_to_exchange_max(qty: int, lot_size: int, max_qty: int = NFO_MAX_ORDER_QTY) -> int:
    """Cap quantity to the exchange freeze while keeping a valid lot multiple."""
    snapped = snap_qty_to_lot(qty, lot_size)
    if snapped <= 0:
        return 0
    cap = snap_qty_to_lot(max_qty, lot_size)
    if cap <= 0:
        return snapped
    return min(snapped, cap)


def chunk_order_qty(qty: int, lot_size: int, max_qty: int = NFO_MAX_ORDER_QTY) -> list[int]:
    """Split a flatten/exit into exchange-legal lot chunks."""
    remaining = snap_qty_to_lot(qty, lot_size)
    lot = max(int(lot_size or 1), 1)
    cap = snap_qty_to_lot(max_qty, lot) or remaining
    chunks: list[int] = []
    while remaining >= lot:
        chunk = min(remaining, cap)
        chunk = snap_qty_to_lot(chunk, lot)
        if chunk <= 0:
            break
        chunks.append(chunk)
        remaining -= chunk
    return chunks
