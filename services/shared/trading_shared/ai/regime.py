"""Market regime detection from live market data."""

from __future__ import annotations

from trading_shared.ai.types import MarketRegime
from trading_shared.strategies.data_provider import StrategyDataProvider


class RegimeDetector:
    def __init__(self, data: StrategyDataProvider):
        self.data = data

    def detect(self, symbol: str = "NIFTY") -> MarketRegime:
        indices = self.data.index_tokens()
        token, _ = indices.get(symbol, (None, None))
        if not token:
            return MarketRegime.RANGING

        tick = self.data.tick(token) or {}
        ltp = float(tick.get("ltp") or 0)
        open_px = float(tick.get("open") or ltp)
        high = float(tick.get("high") or ltp)
        low = float(tick.get("low") or ltp)
        prev_close = float(tick.get("close") or open_px)

        if open_px <= 0:
            return MarketRegime.RANGING

        day_range_pct = ((high - low) / open_px) * 100
        change_pct = ((ltp - prev_close) / prev_close) * 100 if prev_close else 0

        if day_range_pct > 2.0:
            return MarketRegime.HIGH_VOLATILITY
        if day_range_pct < 0.4:
            return MarketRegime.LOW_VOLATILITY
        if change_pct > 0.6:
            return MarketRegime.TRENDING_UP
        if change_pct < -0.6:
            return MarketRegime.TRENDING_DOWN
        return MarketRegime.RANGING
