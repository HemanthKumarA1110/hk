"""Registry of swing desk strategies."""

from __future__ import annotations

from trading_shared.strategies.swing_desk.catalog import catalog_entry
from trading_shared.strategies.swing_desk.strategies.base import SwingStrategy
from trading_shared.strategies.swing_desk.strategies.breakout_atr import BreakoutAtrStrategy
from trading_shared.strategies.swing_desk.strategies.ema_trend import EmaTrendStrategy
from trading_shared.strategies.swing_desk.strategies.rsi_mean_reversion import RsiMeanReversionStrategy

STRATEGY_INSTANCES: dict[str, SwingStrategy] = {
    "ema_trend": EmaTrendStrategy(),
    "rsi_mean_reversion": RsiMeanReversionStrategy(),
    "breakout_atr": BreakoutAtrStrategy(),
}


def get_strategy(strategy_code: str | None = None, strategy_id: str | None = None) -> SwingStrategy:
    if strategy_code:
        entry = catalog_entry(strategy_code)
        if not entry:
            raise ValueError(f"Unknown swing strategy code: {strategy_code}")
        strategy_id = entry["id"]
    if not strategy_id or strategy_id not in STRATEGY_INSTANCES:
        raise ValueError(f"Unknown swing strategy: {strategy_id or strategy_code}")
    return STRATEGY_INSTANCES[strategy_id]
