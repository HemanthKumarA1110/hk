"""Bar-by-bar backtest simulator using production strategy engines."""

from __future__ import annotations

from typing import Callable

import pandas as pd

from trading_shared.backtest.historical_provider import HistoricalDataProvider, evaluate_engine
from trading_shared.backtest.types import BacktestTrade
from trading_shared.risk.engine import RiskEngine, RiskLimits, RiskState


class BacktestSimulator:
    WARMUP = 30

    def __init__(self, initial_capital: float = 100000.0, risk_pct: float = 1.0):
        self.initial_capital = initial_capital
        self.risk_pct = risk_pct

    def run(
        self,
        df: pd.DataFrame,
        engine: str,
        symbol: str,
        token: str,
        max_loss_per_trade_pct: float = 1.0,
        max_daily_loss_pct: float = 5.0,
        max_trades_per_day: int = 10,
        signal_fn: Callable | None = None,
    ) -> dict:
        if len(df) < self.WARMUP + 5:
            raise ValueError(f"Insufficient bars ({len(df)}). Need at least {self.WARMUP + 5}.")

        capital = self.initial_capital
        equity_curve: list[float] = []
        trades: list[BacktestTrade] = []
        limits = RiskLimits(
            max_loss_per_trade_pct=max_loss_per_trade_pct,
            max_daily_loss_pct=max_daily_loss_pct,
            max_trades_per_day=max_trades_per_day,
            risk_per_trade_pct=self.risk_pct,
        )
        risk = RiskEngine(limits, RiskState(equity=capital, peak_equity=capital, available_capital=capital))
        provider = HistoricalDataProvider(df, token, symbol)
        position = None

        for i in range(self.WARMUP, len(df)):
            row = df.iloc[i]
            ts = row.get("timestamp", i)
            current_date = ts.date() if hasattr(ts, "date") else None
            risk.maybe_reset_day(current_date)

            if position is None:
                can_trade, _ = risk.can_trade()
                if not can_trade:
                    equity_curve.append(capital)
                    continue

                provider.set_index(i)
                if signal_fn:
                    signals = signal_fn(provider)
                else:
                    signals = evaluate_engine(engine, provider)

                if not signals:
                    equity_curve.append(capital)
                    continue

                signal = max(signals, key=lambda s: s.score)
                sizing = risk.position_size(signal.entry, signal.stoploss, self.risk_pct)
                qty = sizing["qty"]
                if qty <= 0:
                    equity_curve.append(capital)
                    continue

                position = {
                    "entry_ts": str(ts),
                    "side": signal.side.value if hasattr(signal.side, "value") else str(signal.side),
                    "symbol": signal.symbol,
                    "entry_price": signal.entry,
                    "qty": qty,
                    "stoploss": signal.stoploss,
                    "target": signal.targets[0],
                }
            else:
                exit_price = None
                if position["side"] == "BUY":
                    if row["low"] <= position["stoploss"]:
                        exit_price = position["stoploss"]
                    elif row["high"] >= position["target"]:
                        exit_price = position["target"]
                else:
                    if row["high"] >= position["stoploss"]:
                        exit_price = position["stoploss"]
                    elif row["low"] <= position["target"]:
                        exit_price = position["target"]

                if exit_price is not None:
                    pnl = (
                        (exit_price - position["entry_price"]) * position["qty"]
                        if position["side"] == "BUY"
                        else (position["entry_price"] - exit_price) * position["qty"]
                    )
                    trades.append(
                        BacktestTrade(
                            entry_ts=position["entry_ts"],
                            exit_ts=str(ts),
                            side=position["side"],
                            symbol=position["symbol"],
                            entry_price=position["entry_price"],
                            exit_price=exit_price,
                            qty=position["qty"],
                            pnl=round(pnl, 2),
                            return_pct=round(pnl / (position["entry_price"] * position["qty"]) * 100, 2),
                            stoploss=position["stoploss"],
                            target=position["target"],
                        )
                    )
                    capital += pnl
                    risk.register_trade(pnl, position["entry_price"] * position["qty"])
                    position = None

            equity_curve.append(round(capital, 2))

        return self._build_result(self.initial_capital, capital, equity_curve, trades)

    @staticmethod
    def _build_result(initial_capital: float, capital: float, equity_curve: list[float], trades: list[BacktestTrade]) -> dict:
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        gross_profit = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else round(gross_profit, 2)

        peak = equity_curve[0] if equity_curve else capital
        max_dd = 0.0
        for value in equity_curve:
            if value > peak:
                peak = value
            if peak > 0:
                max_dd = max(max_dd, (peak - value) / peak * 100)

        total_pnl = round(capital - initial_capital, 2)
        return {
            "initial_capital": initial_capital,
            "final_capital": round(capital, 2),
            "equity_curve": equity_curve,
            "trades": [t.to_dict() for t in trades],
            "total_trades": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
            "max_drawdown": round(max_dd, 2),
            "profit_factor": profit_factor,
            "total_pnl": total_pnl,
            "avg_trade_pnl": round(total_pnl / len(trades), 2) if trades else 0.0,
        }
