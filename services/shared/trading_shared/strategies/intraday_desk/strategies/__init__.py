"""Registry of intraday desk strategies."""

from __future__ import annotations

from trading_shared.strategies.intraday_desk.catalog import catalog_entry
from trading_shared.strategies.intraday_desk.strategies.base import IntradayStrategy
from trading_shared.strategies.intraday_desk.strategies.ema_rsi import EmaRsiStrategy
from trading_shared.strategies.intraday_desk.strategies.orb import OpeningRangeBreakout
from trading_shared.strategies.intraday_desk.strategies.vwap_trend import VwapTrendStrategy

STRATEGY_INSTANCES: dict[str, IntradayStrategy] = {
    "orb": OpeningRangeBreakout(),
    "vwap_trend": VwapTrendStrategy(),
    "ema_rsi": EmaRsiStrategy(),
}


def get_strategy(strategy_code: str | None = None, strategy_id: str | None = None) -> IntradayStrategy:
    if strategy_code:
        entry = catalog_entry(strategy_code)
        if not entry:
            raise ValueError(f"Unknown intraday strategy code: {strategy_code}")
        strategy_id = entry["id"]
    if not strategy_id or strategy_id not in STRATEGY_INSTANCES:
        raise ValueError(f"Unknown intraday strategy: {strategy_id or strategy_code}")
    return STRATEGY_INSTANCES[strategy_id]
