#!/usr/bin/env python3
"""Run 60-day evaluation swing backtests on Angel One daily data.

Loads ~14 months for indicator warmup, ranks Nifty 50 by walk-forward preview,
then reports trades closed in the last BACKTEST_DAYS window.

Usage (inside backtesting container with broker connected):

    BACKTEST_USER_ID=1 python scripts/run_swing_angel_backtest.py
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta


def _print_result(code: str, result: dict) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {code} — {result.get('strategy_label', '')}")
    print(f"{'=' * 60}")
    print(f"  Data source       : {result.get('data_source', 'n/a')}")
    print(f"  Universe screened : {result.get('universe_screened', 'n/a')}")
    print(f"  Symbols traded    : {result.get('symbols_traded', 'n/a')} (top {result.get('top_n', 'n/a')})")
    print(f"  Eval window       : last {result.get('evaluation_days', 60)} days")
    print(f"  Trades            : {result.get('total_trades', 0)}")
    print(f"  Win rate          : {result.get('win_rate', 0)}%")
    print(f"  Total P&L         : ₹{result.get('total_pnl', 0):,.2f}")
    print(f"  Profit factor     : {result.get('profit_factor', 0)}")
    print(f"  Max drawdown      : {result.get('max_drawdown', 0)}%")
    print(f"  Avg trade P&L     : ₹{result.get('avg_trade_pnl', 0):,.2f}")
    picks = result.get("picked_stocks") or []
    if picks:
        print("  Top performers:")
        for row in picks[:5]:
            print(
                f"    {row['symbol']:14} score={row.get('score', '—')}  "
                f"trades={row.get('total_trades', 0)}  win={row.get('win_rate', 0)}%  "
                f"pnl=₹{row.get('total_pnl', 0):,.0f}"
            )


def main() -> int:
    user_id = int(os.environ.get("BACKTEST_USER_ID", "1"))
    days = int(os.environ.get("BACKTEST_DAYS", "60"))
    top_n = int(os.environ.get("BACKTEST_TOP_N", "15"))
    capital = float(os.environ.get("BACKTEST_CAPITAL", "100000"))
    max_pos = int(os.environ.get("BACKTEST_MAX_POSITIONS", "5"))
    use_demo = os.environ.get("USE_DEMO_DATA", "0").lower() in {"1", "true", "yes"}

    to_date = date.today()
    from_date = to_date - timedelta(days=days)

    print(f"Swing universe backtest · {days}-day evaluation window")
    print(f"Trade window: {from_date.isoformat()} → {to_date.isoformat()}")
    print(f"User: {user_id} · Angel One daily: {not use_demo} · capital ₹{capital:,.0f}")

    from trading_shared.db.session import SessionLocal
    from trading_shared.backtest.data_loader import BacktestDataLoader
    from trading_shared.strategies.swing_desk.backtest import run_swing_universe_backtest

    db = SessionLocal()
    loader = BacktestDataLoader(db)
    summary: list[tuple[str, dict | None, str | None]] = []

    try:
        for code in ("SWING-EMA", "SWING-RSI", "SWING-BO-ATR"):
            try:
                result = run_swing_universe_backtest(
                    loader,
                    user_id=user_id,
                    strategy_code=code,
                    exchange="NSE",
                    interval="1d",
                    from_date=from_date.isoformat(),
                    to_date=to_date.isoformat(),
                    use_demo_data=use_demo,
                    initial_capital=capital,
                    risk_pct=1.0,
                    max_open_positions=max_pos,
                    top_n=top_n,
                    evaluation_days=days,
                )
                _print_result(code, result)
                summary.append((code, result, None))
            except Exception as exc:
                print(f"\n{code} FAILED: {exc}")
                summary.append((code, None, str(exc)))
    finally:
        db.close()

    print(f"\n{'=' * 60}")
    print("  SUMMARY (sorted by win rate)")
    print(f"{'=' * 60}")
    ok = [item for item in summary if item[1]]
    ok.sort(key=lambda x: (x[1].get("win_rate", 0), x[1].get("total_pnl", 0)), reverse=True)
    for code, result, _ in ok:
        assert result is not None
        print(
            f"  {code:14} win={result['win_rate']:>5}%  "
            f"PF={result['profit_factor']:>5}  P&L=₹{result['total_pnl']:>10,.0f}  "
            f"trades={result['total_trades']}"
        )
    failed = [item for item in summary if item[2]]
    for code, _, err in failed:
        print(f"  {code:14} FAILED — {err}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
