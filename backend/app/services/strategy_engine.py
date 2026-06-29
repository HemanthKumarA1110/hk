"""Strategy engine skeleton. Individual strategies implemented as modules under
`app/strategies/` and loaded/managed here.
"""
from typing import Dict, Any

class StrategyEngine:
    def __init__(self):
        self.strategies = {}

    def register(self, name: str, fn):
        self.strategies[name] = fn

    def run(self, name: str, market_data: Dict[str, Any]):
        if name not in self.strategies:
            raise ValueError("strategy not found")
        return self.strategies[name](market_data)

strategy_engine = StrategyEngine()

# Auto-register built-in strategies
try:
    from app.strategies import scalping, intraday, swing, options_strategy
    strategy_engine.register('scalping', scalping.generate_signals)
    strategy_engine.register('intraday', intraday.generate_signals)
    strategy_engine.register('swing', swing.generate_signals)
    strategy_engine.register('options', options_strategy.generate_option_signal)
except Exception:
    # ignore import errors during initial setup
    pass
