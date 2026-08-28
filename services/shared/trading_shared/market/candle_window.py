"""IST-aware Angel One historical candle request windows."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)


def angel_candle_window(
    from_date: str,
    to_date: str,
    *,
    now: datetime | None = None,
) -> tuple[str, str] | None:
    """Build Angel One getCandleData bounds in IST; None if the window is invalid."""
    now = now or datetime.now(IST)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)

    start_day = datetime.strptime(from_date[:10], "%Y-%m-%d").date()
    end_day = datetime.strptime(to_date[:10], "%Y-%m-%d").date()
    today = now.date()
    if start_day > today:
        return None
    if end_day > today:
        end_day = today

    open_dt = datetime.combine(start_day, datetime.min.time(), tzinfo=IST).replace(
        hour=MARKET_OPEN[0], minute=MARKET_OPEN[1]
    )
    close_dt = datetime.combine(end_day, datetime.min.time(), tzinfo=IST).replace(
        hour=MARKET_CLOSE[0], minute=MARKET_CLOSE[1]
    )
    if start_day == today and now < open_dt:
        return None
    if end_day == today:
        close_dt = min(close_dt, now)
    if open_dt >= close_dt:
        return None
    return open_dt.strftime("%Y-%m-%d %H:%M"), close_dt.strftime("%Y-%m-%d %H:%M")


def classify_angel_chunk_error(message: str | None) -> str:
    """Classify a candle-chunk failure: skip, rate_limit, or error."""
    lowered = (message or "").lower()
    if "greater than current datetime" in lowered or "from datetime" in lowered:
        return "skip"
    if (
        "rate limit" in lowered
        or "exceeding access rate" in lowered
        or "couldn't parse the json response" in lowered
    ):
        return "rate_limit"
    return "error"


def angel_rate_limit_wait_sec(attempt: int, base_sec: float = 25.0) -> float:
    """Backoff for Angel One historical-candle rate limits (capped at 90s)."""
    return min(90.0, base_sec * (attempt + 1))
