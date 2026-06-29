"""Extract AI features from strategy signals and market context."""

from __future__ import annotations

from trading_shared.ai.types import FeatureVector, MarketRegime
from trading_shared.market.redis_bus import MarketRedisBus
from trading_shared.strategies.data_provider import StrategyDataProvider


class FeatureExtractor:
    def __init__(self, data: StrategyDataProvider, redis_bus: MarketRedisBus):
        self.data = data
        self.redis_bus = redis_bus

    def extract(self, signal: dict, regime: MarketRegime) -> FeatureVector:
        token = signal.get("token", "")
        tick = self.data.tick(token) or {}
        chain_underlying = "NIFTY" if "NIFTY" in signal.get("symbol", "") else "BANKNIFTY"
        if signal.get("engine") == "scalping":
            chain = self.data.option_chain(chain_underlying) or {}
        else:
            chain = {}

        ltp = float(tick.get("ltp") or signal.get("entry") or 0)
        open_px = float(tick.get("open") or ltp)
        high = float(tick.get("high") or ltp)
        low = float(tick.get("low") or ltp)
        volume = float(tick.get("volume") or 0)
        oi = float(tick.get("oi") or 0)

        trend = self._score_trend(signal, tick)
        volume_score = min(volume / max(float(tick.get("avg_price") or ltp or 1), 1) * 10, 100)
        volatility = self._score_volatility(open_px, high, low, ltp)
        oi_score = min(oi / 100000 * 100, 100) if oi else 50.0
        greeks_score = self._score_greeks(chain, signal)
        sentiment = self._score_sentiment(chain)
        sector = self._score_sector(signal)
        price_action = self._score_price_action(ltp, high, low, open_px, signal)
        rr = min(float(signal.get("risk_reward") or 1) * 25, 100)
        regime_score = self._score_regime(regime, signal)
        strategy_score = float(signal.get("score") or 0)

        return FeatureVector(
            trend=trend,
            volume=min(volume_score, 100),
            volatility=volatility,
            oi=oi_score,
            greeks=greeks_score,
            sentiment=sentiment,
            sector_strength=sector,
            price_action=price_action,
            risk_reward=rr,
            market_regime=regime_score,
            strategy_score=strategy_score,
        )

    @staticmethod
    def _score_trend(signal: dict, tick: dict) -> float:
        side = signal.get("side", "BUY")
        ltp = float(tick.get("ltp") or signal.get("entry") or 0)
        vwap = float(tick.get("avg_price") or ltp)
        if side == "BUY":
            return 80.0 if ltp >= vwap else 35.0
        return 80.0 if ltp <= vwap else 35.0

    @staticmethod
    def _score_volatility(open_px: float, high: float, low: float, ltp: float) -> float:
        if open_px <= 0:
            return 50.0
        day_range_pct = ((high - low) / open_px) * 100
        if day_range_pct < 0.5:
            return 30.0
        if day_range_pct > 2.5:
            return 85.0
        return 60.0

    @staticmethod
    def _score_greeks(chain: dict, signal: dict) -> float:
        rows = chain.get("rows") or []
        if isinstance(rows, dict):
            rows = list(rows.values())
        if not rows:
            return 50.0
        deltas = [abs(float(r.get("delta") or 0)) for r in rows if r.get("delta")]
        if not deltas:
            return 50.0
        avg_delta = sum(deltas) / len(deltas)
        return min(avg_delta * 200, 100)

    @staticmethod
    def _score_sentiment(chain: dict) -> float:
        pcr = chain.get("pcr")
        if pcr is None:
            return 50.0
        if 0.8 <= pcr <= 1.2:
            return 70.0
        if pcr > 1.3:
            return 75.0
        if pcr < 0.7:
            return 65.0
        return 50.0

    def _score_sector(self, signal: dict) -> float:
        sectors = self.data.sector_strength()
        from trading_shared.market.scrip_master import SECTOR_MAP

        sector = SECTOR_MAP.get(signal.get("symbol", ""), "Other")
        if not sectors or sector not in sectors:
            return 50.0
        ranked = list(sectors.values())
        value = sectors[sector]
        if not ranked:
            return 50.0
        percentile = (value - min(ranked)) / max(max(ranked) - min(ranked), 0.01)
        return min(max(percentile * 100, 0), 100)

    @staticmethod
    def _score_price_action(ltp: float, high: float, low: float, open_px: float, signal: dict) -> float:
        if high <= low:
            return 50.0
        position = (ltp - low) / (high - low)
        side = signal.get("side", "BUY")
        if side == "BUY":
            return position * 100
        return (1 - position) * 100

    @staticmethod
    def _score_regime(regime: MarketRegime, signal: dict) -> float:
        side = signal.get("side", "BUY")
        if regime == MarketRegime.TRENDING_UP and side == "BUY":
            return 85.0
        if regime == MarketRegime.TRENDING_DOWN and side == "SELL":
            return 85.0
        if regime == MarketRegime.RANGING:
            return 45.0
        if regime == MarketRegime.HIGH_VOLATILITY:
            return 70.0 if signal.get("engine") == "scalping" else 40.0
        return 55.0
