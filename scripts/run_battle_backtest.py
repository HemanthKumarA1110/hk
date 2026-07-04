"""Run battle-tested scalp backtests (Nifty + BankNifty). Usage inside strategy-engine container."""

from __future__ import annotations

from trading_shared.backtest.data_loader import BacktestDataLoader
from trading_shared.strategies.scalping_desk.backtest import run_backtest
from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS


def _print_result(label: str, r: dict) -> None:
    print(f"\n=== {label} ===")
    if r.get("message"):
        print("message:", r["message"])
    print(
        f"trades={r.get('total_trades')}  win_rate={r.get('win_rate')}%  "
        f"pnl=₹{r.get('total_pnl')}  PF={r.get('profit_factor')}  "
        f"DD=₹{r.get('max_drawdown')} ({r.get('max_drawdown_pct')}%)  "
        f"Sharpe={r.get('sharpe_ratio')}"
    )


def main() -> None:
    loader = BacktestDataLoader(None)
    capital = 100_000

    for instrument_key, underlying in (("nifty50", "NIFTY"), ("banknifty", "BANKNIFTY")):
        df = loader._generate_demo(underlying, "1m", "2025-05-01", "2025-06-20")
        lot = INSTRUMENTS[instrument_key]["lot_size"]

        ema = run_backtest(
            df,
            "1m",
            lot,
            capital,
            instrument_key=instrument_key,
            strategy_family="battle",
            strategy_mode="manual",
            fixed_strategy_id="ema_crossover_rsi",
            max_trades_per_day=3,
        )
        _print_result(f"{instrument_key} · EMA Crossover + RSI", ema)

        if instrument_key == "banknifty":
            orb = run_backtest(
                df,
                "1m",
                lot,
                capital,
                instrument_key=instrument_key,
                strategy_family="battle",
                strategy_mode="manual",
                fixed_strategy_id="orb_breakout",
                max_trades_per_day=3,
            )
            _print_result(f"{instrument_key} · ORB Breakout", orb)


if __name__ == "__main__":
    main()
