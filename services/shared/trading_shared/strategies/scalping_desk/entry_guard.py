"""Redis locks so scalping auto cannot place the same live entry twice."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

ENTRY_LOCK_TTL_SEC = 45
ENTRY_COOLDOWN_TTL_SEC = 90
EVAL_LOCK_TTL_SEC = 25

IST = ZoneInfo("Asia/Kolkata")
_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
# NIFTY18AUG2624200PE / BANKNIFTY25AUG2648000CE
_OPT_EXPIRY_RE = re.compile(
    r"^(?:BANKNIFTY|NIFTY|FINNIFTY|MIDCPNIFTY)(\d{2})([A-Z]{3})(\d{2})",
    re.IGNORECASE,
)


def entry_lock_key(user_id: int, instrument_key: str) -> str:
    return f"scalping:entry_lock:{user_id}:{instrument_key}"


def entry_cooldown_key(user_id: int, instrument_key: str) -> str:
    return f"scalping:entry_cooldown:{user_id}:{instrument_key}"


def eval_lock_key(user_id: int, instrument_key: str) -> str:
    return f"scalping:eval_lock:{user_id}:{instrument_key}"


def try_acquire_lock(client: Any, key: str, ttl_sec: int) -> bool:
    return bool(client.set(key, "1", nx=True, ex=int(ttl_sec)))


def release_lock(client: Any, key: str) -> None:
    try:
        client.delete(key)
    except Exception:
        return


def set_entry_cooldown(client: Any, user_id: int, instrument_key: str, ttl_sec: int = ENTRY_COOLDOWN_TTL_SEC) -> None:
    client.setex(entry_cooldown_key(user_id, instrument_key), int(ttl_sec), "1")


def entry_cooldown_active(client: Any, user_id: int, instrument_key: str) -> bool:
    return bool(client.get(entry_cooldown_key(user_id, instrument_key)))


def _symbol_matches_underlying(symbol: str, underlying: str) -> bool:
    sym = str(symbol or "").upper()
    name = str(underlying or "").upper()
    if name == "BANKNIFTY":
        return sym.startswith("BANKNIFTY")
    if name == "NIFTY":
        return sym.startswith("NIFTY") and not sym.startswith("BANKNIFTY")
    return bool(name) and sym.startswith(name)


def parse_option_expiry(symbol: str) -> date | None:
    """Parse DDMMMYY expiry from an Angel One index-option trading symbol."""
    match = _OPT_EXPIRY_RE.match(str(symbol or "").upper())
    if not match:
        return None
    day = int(match.group(1))
    month = _MONTHS.get(match.group(2))
    year = 2000 + int(match.group(3))
    if not month:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def option_symbol_is_expired(symbol: str, *, as_of: date | None = None) -> bool:
    """True when the contract expiry is strictly before the IST trading day."""
    expiry = parse_option_expiry(symbol)
    if expiry is None:
        return False
    today = as_of or datetime.now(IST).date()
    return expiry < today


def live_net_qty(db: Any, user_id: int, symbol: str) -> int:
    """Net BUY-SELL qty already sent live for this contract."""
    return _live_net_qty(db, user_id, symbol=symbol)


def live_underlying_net_qty(db: Any, user_id: int, underlying: str) -> int:
    """Net live option qty for the desk underlying (blocks stacking after a fill)."""
    return _live_net_qty(db, user_id, underlying=underlying)


def _live_net_qty(
    db: Any,
    user_id: int,
    *,
    symbol: str | None = None,
    underlying: str | None = None,
) -> int:
    from trading_shared.models.order import BrokerOrder

    rows = (
        db.query(BrokerOrder)
        .filter(
            BrokerOrder.user_id == user_id,
            BrokerOrder.execution_mode == "live",
            BrokerOrder.status.in_(("submitted", "open", "complete", "filled", "executed")),
        )
        .all()
    )
    net = 0
    want = str(symbol or "").upper()
    today = datetime.now(IST).date()
    for row in rows:
        row_symbol = str(row.symbol or "").upper()
        if want and row_symbol != want:
            continue
        if underlying and not _symbol_matches_underlying(row_symbol, underlying):
            continue
        # Expired contracts must not permanently block new live entries.
        if option_symbol_is_expired(row_symbol, as_of=today):
            continue
        qty = int(row.qty or 0)
        if str(row.side or "").upper() == "BUY":
            net += qty
        else:
            net -= qty
    return net
