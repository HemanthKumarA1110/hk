#!/usr/bin/env python3
"""Run 60-day evaluation scalping backtests on Angel One 1m index data.

Loads ~70 calendar days of NIFTY / BANKNIFTY 1m candles (chunked for Angel limits),
replays each SCALP-* catalog strategy, and reports trades closed in the eval window.

Usage (inside backtesting container with broker connected):

    BACKTEST_USER_ID=1 python scripts/run_scalping_angel_backtest.py

Optional env:
    BACKTEST_DAYS=60
    BACKTEST_CAPITAL=100000
    USE_DEMO_DATA=0
    INCLUDE_SMC=0
    CHUNK_DAYS=5
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime, timedelta

import pandas as pd

BATTLE_ADAPTIVE_CODES = (
    "SCALP-BT-001",
    "SCALP-BT-002",
    "SCALP-AD-001",
    "SCALP-AD-002",
    "SCALP-AD-003",
    "SCALP-AD-004",
)

SMC_CODES = ("SCALP-SMC-001", "SCALP-SMC-002", "SCALP-SMC-003")

INSTRUMENTS = (
    ("nifty50", "NIFTY"),
    ("banknifty", "BANKNIFTY"),
)


def _print_result(inst: str, code: str, result: dict) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {inst.upper()} · {code} — {result.get('strategy_label', '')}")
    print(f"{'=' * 60}")
    print(f"  Bars processed    : {result.get('bars_processed', result.get('bars_loaded', 'n/a'))}")
    print(f"  Eval window       : last {result.get('evaluation_days', 60)} days")
    print(f"  Trades            : {result.get('total_trades', 0)}")
    print(f"  Win rate          : {result.get('win_rate', 0)}%")
    print(f"  Total P&L         : ₹{result.get('total_pnl', 0):,.2f}")
    print(f"  Profit factor     : {result.get('profit_factor', 0)}")
    print(f"  Max drawdown      : {result.get('max_drawdown', 0)}")
    print(f"  Avg trade P&L     : ₹{result.get('avg_trade_pnl', 0):,.2f}")
    if result.get("message"):
        print(f"  Note              : {result['message']}")


async def load_index_candles_chunked(
    loader,
    user_id: int,
    underlying: str,
    from_date: str,
    to_date: str,
    *,
    interval: str = "1m",
    chunk_days: int = 5,
    use_demo: bool = False,
) -> tuple[pd.DataFrame, str]:
    """Load index OHLCV in small chunks to stay within Angel One 1m limits."""
    if use_demo:
        df, source = loader.load(
            user_id,
            underlying,
            None,
            "NSE",
            interval,
            from_date[:10],
            to_date[:10],
            use_demo_data=True,
        )
        return df, source

    start = datetime.strptime(from_date[:10], "%Y-%m-%d").date()
    end = datetime.strptime(to_date[:10], "%Y-%m-%d").date()
    frames: list[pd.DataFrame] = []
    source = "unknown"
    cur = start
    while cur <= end:
        chunk_end = min(cur + timedelta(days=chunk_days - 1), end)
        df, src = await loader.load_candles_async(
            user_id,
            underlying,
            None,
            "NSE",
            interval,
            cur.isoformat(),
            chunk_end.isoformat(),
        )
        if not df.empty:
            frames.append(df)
            source = src
        cur = chunk_end + timedelta(days=1)

    if not frames:
        return pd.DataFrame(), source

    merged = pd.concat(frames, ignore_index=True)
    merged["timestamp"] = pd.to_datetime(merged["timestamp"], errors="coerce")
    merged = merged.dropna(subset=["timestamp"])
    merged = merged.drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    return merged, source


def main() -> int:
    user_id = int(os.environ.get("BACKTEST_USER_ID", "1"))
    days = int(os.environ.get("BACKTEST_DAYS", "60"))
    capital = float(os.environ.get("BACKTEST_CAPITAL", "100000"))
    chunk_days = int(os.environ.get("CHUNK_DAYS", "5"))
    use_demo = os.environ.get("USE_DEMO_DATA", "0").lower() in {"1", "true", "yes"}
    include_smc = os.environ.get("INCLUDE_SMC", "0").lower() in {"1", "true", "yes"}

    to_date = date.today()
    load_from = to_date - timedelta(days=days + 10)
    eval_from = to_date - timedelta(days=days)

    codes = list(BATTLE_ADAPTIVE_CODES)
    if include_smc:
        codes.extend(SMC_CODES)

    print(f"Scalping index backtest · {days}-day evaluation window")
    print(f"Load window: {load_from.isoformat()} → {to_date.isoformat()}")
    print(f"Eval trades closed: {eval_from.isoformat()} → {to_date.isoformat()}")
    print(f"User: {user_id} · Angel One 1m: {not use_demo} · capital ₹{capital:,.0f}")

    from trading_shared.db.session import SessionLocal
    from trading_shared.backtest.data_loader import BacktestDataLoader
    from trading_shared.strategies.scalping_desk.backtest import run_strategy_backtest
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS as INST_META
    from trading_shared.strategies.scalping_desk.strategy_catalog import catalog_entry

    db = SessionLocal()
    loader = BacktestDataLoader(db)
    summary: list[tuple[str, str, dict | None, str | None]] = []

    async def run_all() -> None:
        for inst_key, underlying in INSTRUMENTS:
            try:
                candles, data_source = await load_index_candles_chunked(
                    loader,
                    user_id,
                    underlying,
                    load_from.isoformat(),
                    to_date.isoformat(),
                    interval="1m",
                    chunk_days=chunk_days,
                    use_demo=use_demo,
                )
            except Exception as exc:
                print(f"\n{inst_key} candle load FAILED: {exc}")
                for code in codes:
                    entry = catalog_entry(code)
                    if entry and inst_key not in entry.get("instruments", []):
                        continue
                    summary.append((inst_key, code, None, str(exc)))
                continue

            print(f"\n>>> {inst_key.upper()} — {len(candles)} bars loaded ({data_source})")
            lot_size = int(INST_META[inst_key]["lot_size"])

            for code in codes:
                entry = catalog_entry(code)
                if not entry or inst_key not in entry.get("instruments", []):
                    continue
                try:
                    result = run_strategy_backtest(
                        candles,
                        "1m",
                        lot_size,
                        capital,
                        strategy_code=code,
                        instrument_key=inst_key,
                        max_loss_per_day=5000,
                        max_trades_per_day=3,
                        evaluation_days=days,
                    )
                    result["data_source"] = data_source
                    result["bars_loaded"] = len(candles)
                    _print_result(inst_key, code, result)
                    summary.append((inst_key, code, result, None))
                except Exception as exc:
                    print(f"\n{inst_key} · {code} FAILED: {exc}")
                    summary.append((inst_key, code, None, str(exc)))

    try:
        asyncio.run(run_all())
    finally:
        db.close()

    print(f"\n{'=' * 60}")
    print("  SUMMARY (sorted by win rate, min 1 trade)")
    print(f"{'=' * 60}")
    ok = [item for item in summary if item[2] and item[2].get("total_trades", 0) > 0]
    ok.sort(
        key=lambda x: (x[2].get("win_rate", 0), x[2].get("total_pnl", 0)),
        reverse=True,
    )
    for inst_key, code, result, _ in ok:
        assert result is not None
        print(
            f"  {inst_key:10} {code:14} win={result['win_rate']:>5}%  "
            f"PF={result['profit_factor']:>5}  P&L=₹{result['total_pnl']:>10,.0f}  "
            f"trades={result['total_trades']}"
        )

    zero = [item for item in summary if item[2] and item[2].get("total_trades", 0) == 0]
    for inst_key, code, result, _ in zero:
        msg = (result or {}).get("message", "no trades")
        print(f"  {inst_key:10} {code:14} — 0 trades ({msg})")

    failed = [item for item in summary if item[3]]
    for inst_key, code, _, err in failed:
        print(f"  {inst_key:10} {code:14} FAILED — {err}")

    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
