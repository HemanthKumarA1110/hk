#!/usr/bin/env python3
"""Run 60-day Angel One intraday backtests for all desk strategies.

Usage (inside strategy-engine or backtesting container with broker connected):

    BACKTEST_USER_ID=1 python scripts/run_intraday_angel_backtest.py

Optional env:
    BACKTEST_DAYS=60
    BACKTEST_TOP_N=10
    BACKTEST_CAPITAL=100000
    USE_DEMO_DATA=0
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta


def _print_result(code: str, result: dict) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {code} — {result.get('strategy_label', '')}")
    print(f"{'=' * 60}")
    print(f"  Data source     : {result.get('data_source', 'n/a')}")
    print(f"  Universe        : {result.get('universe_screened', 'n/a')} screened · top {result.get('top_n', 'n/a')}")
    print(f"  Trades          : {result.get('total_trades', 0)}")
    print(f"  Win rate        : {result.get('win_rate', 0)}%")
    print(f"  Total P&L       : ₹{result.get('total_pnl', 0):,.2f}")
    print(f"  Profit factor   : {result.get('profit_factor', 0)}")
    print(f"  Max drawdown    : {result.get('max_drawdown', 0)}%")
    print(f"  Avg trade P&L   : ₹{result.get('avg_trade_pnl', 0):,.2f}")
    picks = result.get("picked_stocks") or []
    if picks:
        print("  Top picks:")
        for row in picks[:5]:
            print(
                f"    {row['symbol']:14} score={row.get('score', 0):>6}  "
                f"trades={row.get('total_trades', 0)}  win={row.get('win_rate', 0)}%  "
                f"pnl=₹{row.get('total_pnl', 0):,.0f}"
            )


def main() -> int:
    user_id = int(os.environ.get("BACKTEST_USER_ID", "1"))
    days = int(os.environ.get("BACKTEST_DAYS", "60"))
    top_n = int(os.environ.get("BACKTEST_TOP_N", "10"))
    capital = float(os.environ.get("BACKTEST_CAPITAL", "100000"))
    use_demo = os.environ.get("USE_DEMO_DATA", "0").lower() in {"1", "true", "yes"}

    to_date = date.today()
    from_date = to_date - timedelta(days=days)

    print(f"Intraday universe backtest · last {days} days")
    print(f"Period: {from_date.isoformat()} → {to_date.isoformat()}")
    print(f"User: {user_id} · Angel One data: {not use_demo} · capital ₹{capital:,.0f}")

    from trading_shared.db.session import SessionLocal
    from trading_shared.backtest.data_loader import BacktestDataLoader
    from trading_shared.strategies.intraday_desk.backtest import run_intraday_universe_backtest

    db = SessionLocal()
    loader = BacktestDataLoader(db)
    summary: list[tuple[str, dict | None, str | None]] = []

    try:
        for code in ("INTRA-ORB", "INTRA-VWAP-ORB"):
            try:
                result = run_intraday_universe_backtest(
                    loader,
                    user_id=user_id,
                    strategy_code=code,
                    exchange="NSE",
                    interval="5m",
                    from_date=from_date.isoformat(),
                    to_date=to_date.isoformat(),
                    use_demo_data=use_demo,
                    initial_capital=capital,
                    risk_pct=1.0,
                    top_n=top_n,
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
    for code, result, err in ok:
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
