#!/usr/bin/env python3
"""Compare CE/PE Buy-only vs Buy+Sell on Angel One 60d scalping backtests.

Usage (strategy-engine container):
    BACKTEST_USER_ID=1 python /app/scripts/compare_option_buy_vs_sell.py

Optional env:
    BACKTEST_DAYS=60
    BACKTEST_CAPITAL=100000
    INCLUDE_SMC=1
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta

from trading_shared.strategies.scalping_desk.option_execution import (
    OPTION_EXECUTION_BUY_AND_SELL,
    OPTION_EXECUTION_BUY_ONLY,
    execution_mode_label,
)
from trading_shared.strategies.scalping_desk.strategy_catalog import catalog_for_instrument

INSTRUMENTS = (("nifty50", "NIFTY"), ("banknifty", "BANKNIFTY"))
MODES = (
    (OPTION_EXECUTION_BUY_ONLY, "buy"),
    (OPTION_EXECUTION_BUY_AND_SELL, "buy_sell"),
)


def _codes(inst_key: str, include_smc: bool) -> list[str]:
    return [
        m["code"]
        for m in catalog_for_instrument(inst_key)
        if include_smc or m.get("family") != "smc"
    ]


async def _load_candles(user_id: int, inst_key: str, load_from, to_date):
    from trading_shared.db.session import SessionLocal
    from trading_shared.strategies.scalping_desk.service import ScalpingDeskService

    db = SessionLocal()
    try:
        svc = ScalpingDeskService(db, user_id, inst_key)
        df, source, notes = await svc._load_desk_backtest_candles(
            load_from.isoformat(),
            to_date.isoformat(),
            "1m",
        )
        if notes:
            print(f"  {inst_key} load notes: {'; '.join(notes)}")
        return df, source
    finally:
        db.close()


def main() -> int:
    user_id = int(os.environ.get("BACKTEST_USER_ID", "1"))
    days = int(os.environ.get("BACKTEST_DAYS", "60"))
    capital = float(os.environ.get("BACKTEST_CAPITAL", "100000"))
    chunk_days = int(os.environ.get("CHUNK_DAYS", "5"))
    include_smc = os.environ.get("INCLUDE_SMC", "0").lower() in {"1", "true", "yes"}

    to_date = date.today()
    load_from = to_date - timedelta(days=days + 10)

    from trading_shared.db.session import SessionLocal
    from trading_shared.strategies.scalping_desk.backtest import run_strategy_backtest
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS as INST_META

    rows: list[dict] = []

    async def run_all() -> None:
        for inst_key, _underlying in INSTRUMENTS:
            try:
                candles, source = await _load_candles(user_id, inst_key, load_from, to_date)
            except Exception as exc:
                print(f"{inst_key} load failed: {exc}")
                continue
            if candles.empty:
                print(f"{inst_key}: no candles")
                continue
            lot_size = int(INST_META[inst_key]["lot_size"])
            print(f"\n>>> {inst_key.upper()} · {len(candles)} bars ({source})")
            for code in _codes(inst_key, include_smc):
                for mode, tag in MODES:
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
                            option_execution_mode=mode,
                        )
                        rows.append(
                            {
                                "instrument": inst_key,
                                "code": code,
                                "mode": tag,
                                "mode_label": execution_mode_label(mode),
                                "trades": result.get("total_trades", 0),
                                "win_rate": result.get("win_rate", 0),
                                "pnl": result.get("total_pnl", 0),
                                "pf": result.get("profit_factor", 0),
                                "final_capital": result.get("final_capital", capital),
                                "message": result.get("message"),
                            }
                        )
                    except Exception as exc:
                        rows.append(
                            {
                                "instrument": inst_key,
                                "code": code,
                                "mode": tag,
                                "error": str(exc),
                            }
                        )

    try:
        asyncio.run(run_all())
    finally:
        pass

    print("\n" + "=" * 78)
    print(f"  OPTION EXECUTION COMPARISON · Angel One · last {days} days · ₹{capital:,.0f}")
    print("=" * 78)
    print(f"{'Inst':10} {'Strategy':14} {'Mode':10} {'Trades':>6} {'WR%':>6} {'P&L':>12} {'PF':>5}")
    print("-" * 78)

    buy_total = 0.0
    sell_total = 0.0
    buy_wins = 0
    sell_wins = 0
    pairs = 0

    by_key: dict[tuple[str, str], dict[str, dict]] = {}
    for r in rows:
        if r.get("error"):
            print(f"{r['instrument']:10} {r['code']:14} {r['mode']:10} ERROR — {r['error']}")
            continue
        print(
            f"{r['instrument']:10} {r['code']:14} {r['mode']:10} "
            f"{r['trades']:6d} {r['win_rate']:6.1f} ₹{r['pnl']:11,.0f} {r['pf']:5.2f}"
        )
        by_key.setdefault((r["instrument"], r["code"]), {})[r["mode"]] = r

    for (inst_key, code), modes in sorted(by_key.items()):
        buy = modes.get("buy")
        sell = modes.get("buy_sell")
        if not buy or not sell:
            continue
        if buy["trades"] < 1 and sell["trades"] < 1:
            continue
        pairs += 1
        buy_total += float(buy["pnl"])
        sell_total += float(sell["pnl"])
        if float(sell["pnl"]) > float(buy["pnl"]):
            sell_wins += 1

    print("\n" + "=" * 78)
    print("  AGGREGATE")
    print("=" * 78)
    print(f"  Strategy pairs compared     : {pairs}")
    print(f"  Buy-only total P&L          : ₹{buy_total:,.0f}")
    print(f"  Buy+Sell total P&L          : ₹{sell_total:,.0f}")
    print(f"  Buy+Sell wins (per strategy): {sell_wins} / {pairs}")
    delta = sell_total - buy_total
    print(f"  Delta (Buy+Sell − Buy)      : ₹{delta:,.0f}")

    if pairs and sell_total > buy_total:
        print("\n  RESULT: Buy+Sell is more profitable on 60d Angel data.")
        print("  → Recommend enabling SELL leg in live desk.")
        return 2
    print("\n  RESULT: Buy-only is equal or better — keep buy-only policy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
