#!/usr/bin/env python3
"""Fast win-rate tuning for SCALP-BT-003 on last ~60 days Angel One 1m.

Usage (inside strategy-engine container):

    python /app/scripts/tune_scalp_bt003.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, timedelta

BACKTEST_DAYS = int(os.environ.get("BACKTEST_DAYS", "60"))
SAMPLE_BARS = int(os.environ.get("SAMPLE_BARS", "15000"))
STRATEGY_CODE = "SCALP-BT-003"
INSTRUMENT_KEY = "banknifty"


async def load_candles(user_id: int):
    from trading_shared.db.session import SessionLocal
    from trading_shared.strategies.scalping_desk.service import ScalpingDeskService

    to_date = date.today()
    from_date = (to_date - timedelta(days=BACKTEST_DAYS)).isoformat()
    db = SessionLocal()
    try:
        svc = ScalpingDeskService(db, user_id, INSTRUMENT_KEY)
        df, source, notes = await svc._load_desk_backtest_candles(from_date, to_date.isoformat(), "1m")
        if notes:
            print("notes:", "; ".join(notes))
        if len(df) > SAMPLE_BARS:
            df = df.tail(SAMPLE_BARS).reset_index(drop=True)
        return df, source
    finally:
        db.close()


def main() -> int:
    from trading_shared.strategies.scalping_desk.backtest import run_strategy_backtest
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS
    from trading_shared.strategies.scalping_desk.ema_crossover_tuning import (
        EMA_CROSSOVER_BANK_LEGACY,
        ema_candidate_grid,
        score_ema_backtest,
    )

    user_id = int(os.environ.get("BACKTEST_USER_ID", "1"))
    capital = float(os.environ.get("BACKTEST_CAPITAL", "100000"))
    lot = int(INSTRUMENTS[INSTRUMENT_KEY]["lot_size"])

    print(f"Tuning {STRATEGY_CODE} · {BACKTEST_DAYS}d Angel One · sample={SAMPLE_BARS} bars")
    try:
        candles, source = asyncio.run(load_candles(user_id))
    except Exception as exc:
        print(f"Load failed: {exc}")
        return 1

    print(f"Loaded {len(candles)} bars ({source})")
    if len(candles) < 500:
        print("Insufficient bars.")
        return 1

    best_params = {}
    best_result: dict = {}
    best_score = float("-inf")

    for idx, ema in enumerate(ema_candidate_grid()):
        result = run_strategy_backtest(
            candles,
            "1m",
            lot,
            capital,
            strategy_code=STRATEGY_CODE,
            instrument_key=INSTRUMENT_KEY,
            params={"ema_crossover": ema},
        )
        score = score_ema_backtest(result)
        label = "legacy" if ema == EMA_CROSSOVER_BANK_LEGACY else f"v{idx}"
        print(
            f"{label:>6} trades={result.get('total_trades'):>3} "
            f"WR={result.get('win_rate'):>5}% PF={result.get('profit_factor')} "
            f"PnL=₹{result.get('total_pnl')} score={score:.2f}"
        )
        if score > best_score:
            best_score = score
            best_params = dict(ema)
            best_result = result

    print("\n=== Best params ===")
    print(json.dumps(best_params, indent=2))
    print(
        f"\nBest WR={best_result.get('win_rate')}% trades={best_result.get('total_trades')} "
        f"PF={best_result.get('profit_factor')} PnL=₹{best_result.get('total_pnl')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
