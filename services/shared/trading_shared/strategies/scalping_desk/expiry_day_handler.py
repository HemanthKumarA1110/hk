"""
Expiry day handler for Nifty / Bank Nifty options scalping (2026 calendar).

Deterministic rules matching EXPIRY_DAY_HANDLER_PROMPT; template available for
LLM extensions via `format_expiry_handler_prompt`.

Calendar (2026+):
- Bank Nifty weekly expiry: Wednesday
- Nifty weekly expiry: Thursday
- Nifty monthly expiry: last Thursday of the month
"""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta
from typing import Any

from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS, DEFAULT_MAX_TRADES

IST = __import__("zoneinfo").ZoneInfo("Asia/Kolkata")

EXPIRY_DAY_HANDLER_PROMPT = """Expiry day handler:
Today is {DATE}. Check if today is an options expiry day or special session.

Known expiry pattern for 2026: BankNifty expires every Wednesday, Nifty expires every Thursday, monthly expiry on last Thursday.

Is today: {IS_EXPIRY_DAY} (true/false)
Time to expiry: {HOURS_TO_EXPIRY} hours

If it IS an expiry day, apply the following rules and return recommended adjustments:
- Before 11:00 IST: avoid all scalp trades (pin risk too high)
- 11:00–13:00 IST: trade only with the trend, widen SL by 40%
- After 13:00 IST: gamma spikes — no new trades, manage open positions only
- Max 2 trades total on expiry day

Return JSON: {{"is_expiry":true,"recommended_window":"none|11-13|avoid","max_trades":0,"sl_multiplier":1.0,"warning":"<20 words"}}"""

EXPIRY_MAX_TRADES = 2
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30

WEEKLY_EXPIRY_WEEKDAY = {
    "nifty50": 3,  # Thursday
    "banknifty": 2,  # Wednesday
}


def to_ist(ts: Any = None) -> datetime:
    if ts is None:
        return datetime.now(IST)
    if isinstance(ts, datetime):
        dt = ts
    else:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")) if isinstance(ts, str) else datetime.now(IST)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


def last_thursday(year: int, month: int) -> datetime:
    last_day = calendar.monthrange(year, month)[1]
    dt = datetime(year, month, last_day, tzinfo=IST)
    while dt.weekday() != 3:
        dt -= timedelta(days=1)
    return dt


def is_last_thursday(dt: datetime) -> bool:
    return dt.weekday() == 3 and dt.date() == last_thursday(dt.year, dt.month).date()


def is_nifty_expiry_day(dt: datetime | None = None) -> bool:
    """Nifty weekly (Thu) — includes monthly last Thursday."""
    day = to_ist(dt)
    return day.weekday() == WEEKLY_EXPIRY_WEEKDAY["nifty50"]


def is_banknifty_expiry_day(dt: datetime | None = None) -> bool:
    day = to_ist(dt)
    return day.weekday() == WEEKLY_EXPIRY_WEEKDAY["banknifty"]


def is_instrument_expiry_day(ts: Any, instrument_key: str) -> bool:
    dt = to_ist(ts)
    key = instrument_key.lower()
    if key == "nifty50":
        return is_nifty_expiry_day(dt)
    if key == "banknifty":
        return is_banknifty_expiry_day(dt)
    return False


def is_special_session(ts: Any = None, macro: dict[str, Any] | None = None) -> bool:
    macro = macro or {}
    if macro.get("special_session") or macro.get("is_special_session"):
        return True
    label = str(macro.get("session_type") or "").lower()
    return label in ("muhurat", "special", "holiday_session")


def hours_to_expiry(ts: Any = None) -> float:
    """Hours until 15:30 IST on the given day."""
    now = to_ist(ts)
    close = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0, microsecond=0)
    if now >= close:
        return 0.0
    return round((close - now).total_seconds() / 3600, 2)


def _expiry_window_minutes(now: datetime) -> str:
    minutes = now.hour * 60 + now.minute
    if minutes < 11 * 60:
        return "none"
    if minutes < 13 * 60:
        return "11-13"
    return "avoid"


def format_expiry_handler_prompt(
    *,
    date_str: str,
    is_expiry_day: bool,
    hours_left: float,
) -> str:
    return EXPIRY_DAY_HANDLER_PROMPT.format(
        DATE=date_str,
        IS_EXPIRY_DAY=str(is_expiry_day).lower(),
        HOURS_TO_EXPIRY=hours_left,
    )


def handle_expiry_day(
    instrument_key: str,
    ts: Any = None,
    *,
    macro: dict[str, Any] | None = None,
    default_max_trades: int = DEFAULT_MAX_TRADES,
    trend_direction: str | None = None,
) -> dict[str, Any]:
    """
    Return expiry / special-session adjustments for the desk.
    """
    now = to_ist(ts)
    date_str = now.strftime("%Y-%m-%d (%A)")
    expiry = is_instrument_expiry_day(now, instrument_key)
    special = is_special_session(now, macro)
    monthly = is_last_thursday(now) if instrument_key == "nifty50" and expiry else False
    hrs = hours_to_expiry(now) if expiry or special else 0.0

    prompt = format_expiry_handler_prompt(
        date_str=date_str,
        is_expiry_day=expiry or special,
        hours_left=hrs,
    )

    if not expiry and not special:
        return {
            "is_expiry": False,
            "is_special_session": False,
            "is_monthly_expiry": False,
            "recommended_window": "full",
            "max_trades": int(default_max_trades),
            "sl_multiplier": 1.0,
            "trend_only": False,
            "allowed_directions": "both",
            "warning": "",
            "hours_to_expiry": 0.0,
            "date": date_str,
            "instrument": INSTRUMENTS.get(instrument_key, {}).get("label") or instrument_key,
            "prompt": prompt,
        }

    window = _expiry_window_minutes(now)
    sl_mult = 1.0
    max_trades = EXPIRY_MAX_TRADES
    trend_only = False
    allowed = "both"
    warning = ""

    if window == "none":
        max_trades = 0
        warning = "Expiry AM — pin risk high, no new scalps"
    elif window == "11-13":
        sl_mult = 1.4
        trend_only = True
        allowed = _trend_allowed_directions(trend_direction)
        warning = "Expiry mid-session — trend only, SL +40%"
    else:
        max_trades = 0
        warning = "Expiry afternoon gamma — manage open only"

    if special and not expiry:
        warning = f"Special session — {warning or 'reduced activity'}".strip()
        if window == "none":
            max_trades = 0

    if monthly and expiry:
        warning = f"Monthly expiry — {warning}".strip()[:80]

    return {
        "is_expiry": expiry,
        "is_special_session": special,
        "is_monthly_expiry": monthly,
        "recommended_window": window if expiry or special else "full",
        "max_trades": max_trades,
        "sl_multiplier": sl_mult,
        "trend_only": trend_only,
        "allowed_directions": allowed,
        "warning": warning[:80],
        "hours_to_expiry": hrs,
        "date": date_str,
        "instrument": INSTRUMENTS.get(instrument_key, {}).get("label") or instrument_key,
        "prompt": prompt,
    }


def _trend_allowed_directions(trend_direction: str | None) -> str:
    d = str(trend_direction or "neutral").lower()
    if d == "up":
        return "long_only"
    if d == "down":
        return "short_only"
    return "both"


def expiry_blocks_new_entries(handler: dict[str, Any] | None) -> bool:
    if not handler:
        return False
    if not handler.get("is_expiry") and not handler.get("is_special_session"):
        return False
    window = handler.get("recommended_window")
    if window in ("none", "avoid"):
        return True
    if int(handler.get("max_trades") or 0) <= 0:
        return True
    return False


def expiry_allows_signal(
    handler: dict[str, Any] | None,
    signal_type: str | None,
    *,
    trend_direction: str | None = None,
) -> bool:
    if expiry_blocks_new_entries(handler):
        return False
    if not handler or (not handler.get("is_expiry") and not handler.get("is_special_session")):
        return True
    allowed = handler.get("allowed_directions") or "both"
    if allowed == "both" and handler.get("trend_only"):
        allowed = _trend_allowed_directions(trend_direction)
    st = str(signal_type or "").upper()
    if allowed == "long_only" and st == "PUT":
        return False
    if allowed == "short_only" and st == "CALL":
        return False
    return True


def apply_expiry_to_targets(
    targets: dict[str, Any],
    handler: dict[str, Any] | None,
) -> dict[str, Any]:
    if not handler:
        return targets
    mult = float(handler.get("sl_multiplier") or 1.0)
    if mult == 1.0:
        return targets
    from trading_shared.strategies.scalping_desk.market_regime_classifier import apply_regime_to_targets

    return apply_regime_to_targets(
        targets,
        {"adjustments": {"sl_multiplier": mult}},
    )
