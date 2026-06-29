"""Swing trading engine for daily/weekly setups."""

from __future__ import annotations

from trading_shared.strategies.data_provider import StrategyDataProvider
from trading_shared.strategies.scoring import SWING_MIN_SCORE, confidence_from_score, rank_top, score_confirmations
from trading_shared.strategies.ta import add_common_indicators, ema, macd
from trading_shared.strategies.types import Confirmation, EngineType, SignalSide, StrategySignalCandidate


class SwingEngine:
    def __init__(self, data: StrategyDataProvider):
        self.data = data

    def evaluate(self, limit: int = 10) -> list[StrategySignalCandidate]:
        candidates: list[StrategySignalCandidate] = []
        for token, symbol in self.data.nifty_universe():
            daily = self._prepare_daily(token, symbol)
            if len(daily) < 30:
                continue
            weekly = daily.copy()
            weekly["close"] = daily["close"].rolling(5).mean()
            row = daily.iloc[-1]
            prev = daily.iloc[-2]
            side = SignalSide.BUY if float(row["ema20"]) > float(row["ema50"]) else SignalSide.SELL
            volume_ma20 = float(daily["volume"].rolling(20).mean().iloc[-1] or 0)
            weekly_close_last = float(weekly["close"].iloc[-1])
            weekly_close_prev = float(weekly["close"].iloc[-5])

            confirmations = [
                Confirmation("breakout_retest", self._breakout_retest(daily), 10),
                Confirmation("volume_breakout", float(row["volume"]) > volume_ma20 * 1.5, 10),
                Confirmation(
                    "mtf_alignment",
                    weekly_close_last > weekly_close_prev if side == SignalSide.BUY else weekly_close_last < weekly_close_prev,
                    12,
                ),
                Confirmation(
                    "ma_crossover",
                    float(row["ema20"]) > float(row["ema50"]) if side == SignalSide.BUY else float(row["ema20"]) < float(row["ema50"]),
                    10,
                ),
                Confirmation("darvas_box", self._darvas_breakout(daily), 8),
                Confirmation(
                    "rsi_reversal",
                    (float(row["rsi14"]) > 50 and side == SignalSide.BUY) or (float(row["rsi14"]) < 50 and side == SignalSide.SELL),
                    8,
                ),
                Confirmation("support_accumulation", float(row["close"]) > float(row["low"]) * 1.01, 8),
                Confirmation("fib_pullback", self._fib_zone(daily), 8),
                Confirmation("delivery_volume_proxy", float(row["volume"]) > float(prev["volume"]), 8),
            ]

            score = score_confirmations(confirmations)
            if score < SWING_MIN_SCORE:
                continue

            pct_target = 0.08 if score < 75 else 0.12
            if side == SignalSide.BUY:
                stoploss = float(prev["low"])
                target = float(row["close"]) * (1 + pct_target)
            else:
                stoploss = float(prev["high"])
                target = float(row["close"]) * (1 - pct_target)

            candidates.append(
                StrategySignalCandidate(
                    engine=EngineType.SWING,
                    strategy_name="swing_multi",
                    symbol=symbol,
                    token=token,
                    side=side,
                    entry=round(float(row["close"]), 2),
                    stoploss=round(stoploss, 2),
                    targets=[round(target, 2)],
                    trailing_stop=round(stoploss, 2),
                    timeframe="1d",
                    score=score,
                    confidence=confidence_from_score(score, confirmations),
                    risk_reward=round(abs(target - float(row["close"])) / max(abs(float(row["close"]) - stoploss), 0.01), 2),
                    confirmations=confirmations,
                    metadata={"holding_days": "2-56", "target_pct": round(pct_target * 100, 1)},
                )
            )

        return rank_top(candidates, limit)

    def _prepare_daily(self, token: str, symbol: str):
        df = self.data.build_daily_frame(token, symbol, days=120)
        df = add_common_indicators(df)
        df["ema200"] = ema(df["close"], 200)
        macd_df = macd(df["close"])
        return df.join(macd_df)

    @staticmethod
    def _breakout_retest(df) -> bool:
        if len(df) < 10:
            return False
        recent_high = float(df["high"].iloc[-10:-1].max())
        last = df.iloc[-1]
        return bool(float(last["close"]) > recent_high * 0.995 and float(last["low"]) <= recent_high * 1.01)

    @staticmethod
    def _darvas_breakout(df) -> bool:
        if len(df) < 20:
            return False
        box_high = float(df["high"].iloc[-20:-1].max())
        return bool(float(df["close"].iloc[-1]) > box_high)

    @staticmethod
    def _fib_zone(df) -> bool:
        if len(df) < 20:
            return False
        swing_high = float(df["high"].iloc[-20:].max())
        swing_low = float(df["low"].iloc[-20:].min())
        if swing_high <= swing_low:
            return False
        fib_618 = swing_high - (swing_high - swing_low) * 0.618
        last_close = float(df["close"].iloc[-1])
        return bool(abs(last_close - fib_618) / fib_618 < 0.02)
