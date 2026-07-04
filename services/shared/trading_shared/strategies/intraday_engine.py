"""Live intraday signal engine using modular desk strategies."""

from __future__ import annotations

from trading_shared.strategies.data_provider import StrategyDataProvider
from trading_shared.strategies.intraday_desk.catalog import enabled_strategy_codes, merge_strategy_settings
from trading_shared.strategies.intraday_desk.session import enrich_intraday_frame, is_force_exit_bar, trading_date
from trading_shared.strategies.intraday_desk.strategies import get_strategy
from trading_shared.strategies.scoring import rank_top
from trading_shared.strategies.types import Confirmation, EngineType, SignalSide, StrategySignalCandidate


class IntradayEngine:
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
        """Evaluate enabled intraday strategies across the universe."""
        if confirmation_filter and not strategy_filter:
            strategy_filter = confirmation_filter

        active_codes = enabled_strategy_codes(self.config)
        if strategy_filter:
            from trading_shared.strategies.intraday_desk.catalog import strategy_id_for_code

            target_id = strategy_id_for_code(strategy_filter) if strategy_filter.startswith("INTRA-") else strategy_filter
            active_codes = [c for c in active_codes if strategy_id_for_code(c) == target_id]

        universe = self._build_universe()
        candidates: list[StrategySignalCandidate] = []

        for token, symbol in universe:
            raw = self.data.build_intraday_frame(token, symbol, bars=80)
            if len(raw) < 25:
                continue
            if "timestamp" not in raw.columns:
                continue

            df = enrich_intraday_frame(raw)
            idx = len(df) - 1
            row = df.iloc[idx]
            if is_force_exit_bar(row["timestamp"]):
                continue

            day = trading_date(row["timestamp"])
            day_bars = df[df["trade_date"] == day]
            traded_today = False

            for code in active_codes:
                strategy = get_strategy(strategy_code=code)
                signal = strategy.try_entry(df, idx, traded_today)
                if not signal:
                    continue

                side = SignalSide.BUY if signal.side == "BUY" else SignalSide.SELL
                rr = abs(signal.target - signal.entry) / max(abs(signal.entry - signal.stoploss), 0.01)
                candidates.append(
                    StrategySignalCandidate(
                        engine=EngineType.INTRADAY,
                        strategy_name=strategy.id,
                        symbol=symbol,
                        token=token,
                        side=side,
                        entry=round(signal.entry, 2),
                        stoploss=round(signal.stoploss, 2),
                        targets=[round(signal.target, 2)],
                        trailing_stop=round(signal.stoploss, 2),
                        timeframe="5m",
                        score=100.0,
                        confidence=0.85,
                        risk_reward=round(rr, 2),
                        confirmations=[Confirmation(strategy.id, True, 100, code)],
                        metadata={"strategy_code": code, "bars_today": len(day_bars)},
                    )
                )
                break

        return rank_top(candidates, limit)

    def _build_universe(self) -> list[tuple[str, str]]:
        hits = self.data.scan_hits()
        universe: dict[str, tuple[str, str]] = {}
        for hit in hits:
            universe[hit["symbol"]] = (hit["token"], hit["symbol"])
        for token, symbol in self.data.nifty_universe()[:20]:
            universe.setdefault(symbol, (token, symbol))
        return list(universe.values())
