"""Swing trading signal engine using modular desk strategies."""

from __future__ import annotations

import pandas as pd

from trading_shared.strategies.data_provider import StrategyDataProvider
from trading_shared.strategies.scoring import rank_top
from trading_shared.strategies.swing_desk.catalog import enabled_strategy_codes, merge_strategy_settings
from trading_shared.strategies.swing_desk.session import enrich_swing_frame
from trading_shared.strategies.swing_desk.strategies import get_strategy
from trading_shared.strategies.types import Confirmation, EngineType, SignalSide, StrategySignalCandidate


class SwingEngine:
    def __init__(self, data: StrategyDataProvider, config: dict | None = None):
        self.data = data
        self.config = config or {}
        self._strategy_settings = merge_strategy_settings(self.config)

    def evaluate(
        self,
        limit: int = 10,
        strategy_filter: str | None = None,
        confirmation_filter: str | None = None,
    ) -> list[StrategySignalCandidate]:
        if confirmation_filter and not strategy_filter:
            strategy_filter = confirmation_filter

        active_codes = enabled_strategy_codes(self.config)
        if strategy_filter:
            from trading_shared.strategies.swing_desk.catalog import strategy_id_for_code

            target_id = strategy_id_for_code(strategy_filter) if str(strategy_filter).startswith("SWING-") else strategy_filter
            active_codes = [c for c in active_codes if strategy_id_for_code(c) == target_id]

        candidates: list[StrategySignalCandidate] = []
        for token, symbol in self.data.nifty_universe():
            raw = self.data.build_daily_frame(token, symbol, days=260)
            if len(raw) < 210:
                continue
            if "timestamp" not in raw.columns:
                raw = raw.copy()
                raw["timestamp"] = pd.date_range(end=pd.Timestamp.now(tz="UTC"), periods=len(raw), freq="B")

            df = enrich_swing_frame(raw)
            idx = len(df) - 1
            row = df.iloc[idx]

            for code in active_codes:
                strategy = get_strategy(strategy_code=code)
                signal = strategy.try_entry(df, idx, in_position=False)
                if not signal:
                    continue

                risk = signal.entry - signal.stoploss
                rr = abs(signal.entry * 0.08 / max(risk, 0.01))
                candidates.append(
                    StrategySignalCandidate(
                        engine=EngineType.SWING,
                        strategy_name=strategy.id,
                        symbol=symbol,
                        token=token,
                        side=SignalSide.BUY,
                        entry=round(signal.entry, 2),
                        stoploss=round(signal.stoploss, 2),
                        targets=[round(signal.entry * 1.08, 2)],
                        trailing_stop=round(signal.stoploss, 2),
                        timeframe="1d",
                        score=100.0,
                        confidence=0.85,
                        risk_reward=round(rr, 2),
                        confirmations=[Confirmation(strategy.id, True, 100, code)],
                        metadata={
                            "strategy_code": code,
                            "max_hold_days": signal.max_hold_days,
                            "long_only": True,
                        },
                    )
                )
                break

        return rank_top(candidates, limit)
