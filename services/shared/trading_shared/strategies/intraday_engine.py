"""Intraday stock selection and signal engine."""

from __future__ import annotations

from trading_shared.strategies.data_provider import StrategyDataProvider
from trading_shared.strategies.scoring import INTRADAY_MIN_SCORE, confidence_from_score, rank_top, score_confirmations
from trading_shared.strategies.ta import add_common_indicators, bollinger_bands, macd, supertrend
from trading_shared.strategies.types import Confirmation, EngineType, SignalSide, StrategySignalCandidate


class IntradayEngine:
    def __init__(self, data: StrategyDataProvider):
        self.data = data

    def evaluate(self, limit: int = 10) -> list[StrategySignalCandidate]:
        universe = self._build_universe()
        candidates: list[StrategySignalCandidate] = []
        sectors = self.data.sector_strength()

        for token, symbol in universe:
            df = add_common_indicators(self.data.build_intraday_frame(token, symbol, bars=40))
            if len(df) < 10:
                continue
            macd_df = macd(df["close"])
            df = df.join(macd_df)
            bb = bollinger_bands(df["close"])
            df = df.join(bb)
            df["supertrend"] = supertrend(df)

            row = df.iloc[-1]
            prev = df.iloc[-2]
            side = SignalSide.BUY if row["ema20"] >= row["ema50"] else SignalSide.SELL

            confirmations = [
                Confirmation("relative_volume", self._scan_hit(symbol, "relative_volume"), 12),
                Confirmation("breakout", self._scan_hit(symbol, "breakout") or row["close"] > prev["high"], 10),
                Confirmation("gap", self._scan_hit(symbol, "gap_up") or self._scan_hit(symbol, "gap_down"), 8),
                Confirmation("sector_leader", self._sector_leader(symbol, sectors), 10),
                Confirmation("momentum", self._scan_hit(symbol, "momentum") or 50 <= row["rsi14"] <= 72, 10),
                Confirmation("ema_trend", row["ema20"] > row["ema50"] if side == SignalSide.BUY else row["ema20"] < row["ema50"], 10),
                Confirmation("vwap_trend", row["close"] > row["vwap"] if side == SignalSide.BUY else row["close"] < row["vwap"], 8),
                Confirmation("supertrend", (row["supertrend"] > 0 and side == SignalSide.BUY) or (row["supertrend"] < 0 and side == SignalSide.SELL), 8),
                Confirmation("rsi_pullback", 45 <= row["rsi14"] <= 65, 8),
                Confirmation("macd_momentum", row["macd"] > row["signal"] if side == SignalSide.BUY else row["macd"] < row["signal"], 8),
                Confirmation("bollinger_squeeze_breakout", row["close"] > row["upper"] or row["close"] < row["lower"], 8),
            ]

            score = score_confirmations(confirmations)
            if score < INTRADAY_MIN_SCORE:
                continue

            if side == SignalSide.BUY:
                stoploss = float(prev["low"])
                target = float(row["close"]) + 2 * (float(row["close"]) - stoploss)
            else:
                stoploss = float(prev["high"])
                target = float(row["close"]) - 2 * (stoploss - float(row["close"]))

            candidates.append(
                StrategySignalCandidate(
                    engine=EngineType.INTRADAY,
                    strategy_name="intraday_multi",
                    symbol=symbol,
                    token=token,
                    side=side,
                    entry=round(float(row["close"]), 2),
                    stoploss=round(stoploss, 2),
                    targets=[round(target, 2)],
                    trailing_stop=round(stoploss, 2),
                    timeframe="15m",
                    score=score,
                    confidence=confidence_from_score(score, confirmations),
                    risk_reward=2.0,
                    confirmations=confirmations,
                    metadata={"sector": self._symbol_sector(symbol)},
                )
            )

        return rank_top([c for c in candidates if c.score >= INTRADAY_MIN_SCORE], limit)

    def _build_universe(self) -> list[tuple[str, str]]:
        hits = self.data.scan_hits()
        universe: dict[str, tuple[str, str]] = {}
        for hit in hits:
            universe[hit["symbol"]] = (hit["token"], hit["symbol"])
        for token, symbol in self.data.nifty_universe()[:20]:
            universe.setdefault(symbol, (token, symbol))
        return list(universe.values())

    def _scan_hit(self, symbol: str, scan_type: str) -> bool:
        return any(h.get("symbol") == symbol and h.get("scan_type") == scan_type for h in self.data.scan_hits())

    @staticmethod
    def _sector_leader(symbol: str, sectors: dict[str, float]) -> bool:
        from trading_shared.market.scrip_master import SECTOR_MAP

        sector = SECTOR_MAP.get(symbol)
        if not sector or not sectors:
            return False
        top = list(sectors.keys())[:3]
        return sector in top

    @staticmethod
    def _symbol_sector(symbol: str) -> str:
        from trading_shared.market.scrip_master import SECTOR_MAP

        return SECTOR_MAP.get(symbol, "Other")
