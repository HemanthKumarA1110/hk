#!/usr/bin/env python3
"""Compare strategy-only vs AI-filtered backtests across all desks.

Runs baseline (no AI) vs AI entry+exit for scalping, intraday, and swing strategies
on Angel One data and prints win-rate / P&L comparison.

Usage (inside backtesting container):

    BACKTEST_USER_ID=1 python scripts/run_ai_comparison_backtest.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta

import pandas as pd

from trading_shared.strategies.scalping_desk.strategy_catalog import catalog_for_instrument

SCALP_INSTRUMENTS = (("nifty50", "NIFTY"), ("banknifty", "BANKNIFTY"))
INTRADAY_CODES = ("INTRA-ORB", "INTRA-VWAP", "INTRA-EMA-RSI")
SWING_CODES = ("SWING-EMA", "SWING-RSI", "SWING-BO-ATR")


def _delta(base: dict, ai: dict) -> str:
    if not base.get("total_trades") and not ai.get("total_trades"):
        return "—"
    d = ai.get("win_rate", 0) - base.get("win_rate", 0)
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.1f}pp"


def _print_row(desk: str, label: str, base: dict, ai: dict) -> None:
    print(
        f"  {desk:10} {label:28} "
        f"base {base.get('win_rate', 0):>5.1f}% ({base.get('total_trades', 0):>3} tr) ₹{base.get('total_pnl', 0):>9,.0f}  |  "
        f"AI {ai.get('win_rate', 0):>5.1f}% ({ai.get('total_trades', 0):>3} tr) ₹{ai.get('total_pnl', 0):>9,.0f}  "
        f"Δwin {_delta(base, ai)}"
    )


async def load_scalp_candles(loader, user_id, underlying, load_from, to_date, chunk_days=5):
    frames = []
    source = "unknown"
    cur = load_from
    while cur <= to_date:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), to_date)
        df, src = await loader.load_candles_async(
            user_id, underlying, None, "NSE", "1m", cur.isoformat(), chunk_end.isoformat()
        )
        if not df.empty:
            frames.append(df)
            source = src
        cur = chunk_end + timedelta(days=1)
    if not frames:
        return pd.DataFrame(), source
    merged = pd.concat(frames, ignore_index=True)
    merged["timestamp"] = pd.to_datetime(merged["timestamp"], errors="coerce")
    return (
        merged.dropna(subset=["timestamp"])
        .drop_duplicates(subset=["timestamp"])
        .sort_values("timestamp")
        .reset_index(drop=True),
        source,
    )


async def run_scalping(db, loader, user_id, days, capital) -> list[tuple[str, str, dict, dict]]:
    from trading_shared.strategies.scalping_desk.backtest import run_strategy_backtest
    from trading_shared.strategies.scalping_desk.strategy_catalog import catalog_entry
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

    to_date = date.today()
    load_from = to_date - timedelta(days=days + 10)
    rows: list[tuple[str, str, dict, dict]] = []

    for inst_key, underlying in SCALP_INSTRUMENTS:
        candles, _ = await load_scalp_candles(loader, user_id, underlying, load_from, to_date)
        if candles.empty:
            continue
        lot = int(INSTRUMENTS[inst_key]["lot_size"])
        for code in [m["code"] for m in catalog_for_instrument(inst_key) if m.get("family") != "smc"]:
            entry = catalog_entry(code)
            if not entry or inst_key not in entry.get("instruments", []):
                continue
            label = f"{inst_key}:{code}"
            base = run_strategy_backtest(
                candles, "1m", lot, capital, strategy_code=code, instrument_key=inst_key, evaluation_days=days
            )
            ai = run_strategy_backtest(
                candles,
                "1m",
                lot,
                capital,
                strategy_code=code,
                instrument_key=inst_key,
                evaluation_days=days,
                ai_entry=True,
                ai_exit=True,
            )
            rows.append((label, "scalping", base, ai))
    return rows


def run_intraday(db, loader, user_id, days, capital, top_n) -> list[tuple[str, str, dict, dict]]:
    from trading_shared.strategies.intraday_desk.backtest import run_intraday_universe_backtest

    to_date = date.today()
    from_date = to_date - timedelta(days=days)
    rows = []
    for code in INTRADAY_CODES:
        try:
            base = run_intraday_universe_backtest(
                loader,
                user_id=user_id,
                strategy_code=code,
                exchange="NSE",
                interval="5m",
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
                use_demo_data=False,
                initial_capital=capital,
                risk_pct=1.0,
                top_n=top_n,
            )
            ai = run_intraday_universe_backtest(
                loader,
                user_id=user_id,
                strategy_code=code,
                exchange="NSE",
                interval="5m",
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
                use_demo_data=False,
                initial_capital=capital,
                risk_pct=1.0,
                top_n=top_n,
                ai_entry=True,
                ai_exit=True,
            )
            rows.append((code, "intraday", base, ai))
        except Exception as exc:
            print(f"  intraday {code} skipped: {exc}")
    return rows


def run_swing(db, loader, user_id, days, capital, top_n) -> list[tuple[str, str, dict, dict]]:
    from trading_shared.strategies.swing_desk.backtest import run_swing_universe_backtest

    to_date = date.today()
    from_date = to_date - timedelta(days=days)
    rows = []
    for code in SWING_CODES:
        try:
            base = run_swing_universe_backtest(
                loader,
                user_id=user_id,
                strategy_code=code,
                exchange="NSE",
                interval="1d",
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
                use_demo_data=False,
                initial_capital=capital,
                risk_pct=1.0,
                max_open_positions=5,
                top_n=top_n,
                evaluation_days=days,
            )
            ai = run_swing_universe_backtest(
                loader,
                user_id=user_id,
                strategy_code=code,
                exchange="NSE",
                interval="1d",
                from_date=from_date.isoformat(),
                to_date=to_date.isoformat(),
                use_demo_data=False,
                initial_capital=capital,
                risk_pct=1.0,
                max_open_positions=5,
                top_n=top_n,
                evaluation_days=days,
                ai_entry=True,
                ai_exit=True,
            )
            rows.append((code, "swing", base, ai))
        except Exception as exc:
            print(f"  swing {code} skipped: {exc}")
    return rows


def main() -> int:
    user_id = int(os.environ.get("BACKTEST_USER_ID", "1"))
    days = int(os.environ.get("BACKTEST_DAYS", "60"))
    capital = float(os.environ.get("BACKTEST_CAPITAL", "100000"))
    top_n = int(os.environ.get("BACKTEST_TOP_N", "15"))

    print(f"AI vs Baseline backtest comparison · {days}-day eval · user {user_id}")
    print("=" * 110)
    print(
        f"  {'Desk':10} {'Strategy':28} "
        f"{'Baseline win/trades/P&L':^32} | {'AI entry+exit win/trades/P&L':^32} {'Δ win'}"
    )
    print("-" * 110)

    from trading_shared.db.session import SessionLocal
    from trading_shared.backtest.data_loader import BacktestDataLoader

    db = SessionLocal()
    loader = BacktestDataLoader(db)
    all_rows: list[tuple[str, str, dict, dict]] = []

    try:
        print("\nRunning scalping (1m index)...")
        all_rows.extend(asyncio.run(run_scalping(db, loader, user_id, days, capital)))

        print("Running intraday (5m Nifty 50 universe)...")
        all_rows.extend(run_intraday(db, loader, user_id, days, capital, top_n))

        print("Running swing (1d Nifty 50 universe)...")
        all_rows.extend(run_swing(db, loader, user_id, days, capital, top_n))
    finally:
        db.close()

    improved = 0
    worse = 0
    for label, desk, base, ai in all_rows:
        _print_row(desk, label, base, ai)
        if ai.get("total_trades", 0) > 0 and base.get("total_trades", 0) > 0:
            if ai.get("win_rate", 0) > base.get("win_rate", 0):
                improved += 1
            elif ai.get("win_rate", 0) < base.get("win_rate", 0):
                worse += 1

    print("=" * 110)
    print(f"  Strategies compared: {len(all_rows)}")
    print(f"  AI improved win rate: {improved}  |  AI lower win rate: {worse}")
    base_wins = [b.get("win_rate", 0) for _, _, b, a in all_rows if b.get("total_trades")]
    ai_wins = [a.get("win_rate", 0) for _, _, b, a in all_rows if a.get("total_trades")]
    if base_wins and ai_wins:
        print(f"  Avg win rate — baseline: {sum(base_wins)/len(base_wins):.1f}%  AI: {sum(ai_wins)/len(ai_wins):.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
