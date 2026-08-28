#!/usr/bin/env python3
"""1-year Angel One backtest for SCALP-BT-003 (Bank Nifty EMA crossover).

Fetches history in ~60-day segments to stay within Angel rate limits, then aggregates.

Usage (inside strategy-engine container):

    python /app/scripts/backtest_scalp_bt003_1y.py

Env:
    BACKTEST_USER_ID=1
    BACKTEST_DAYS=365
    SEGMENT_DAYS=60
    SEGMENT_PAUSE_SEC=120
    BACKTEST_CAPITAL=100000
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date, datetime, timedelta

STRATEGY_CODE = "SCALP-BT-003"
INSTRUMENT_KEY = "banknifty"
BACKTEST_DAYS = int(os.environ.get("BACKTEST_DAYS", "365"))
SEGMENT_DAYS = int(os.environ.get("SEGMENT_DAYS", "60"))
SEGMENT_PAUSE_SEC = int(os.environ.get("SEGMENT_PAUSE_SEC", "120"))


def _segments(total_days: int, seg_days: int) -> list[tuple[date, date]]:
    end = date.today()
    start = end - timedelta(days=total_days)
    out: list[tuple[date, date]] = []
    cur = start
    while cur < end:
        seg_end = min(cur + timedelta(days=seg_days - 1), end)
        out.append((cur, seg_end))
        cur = seg_end + timedelta(days=1)
    return out


async def load_segment(user_id: int, from_d: date, to_d: date):
    import trading_shared.strategies.scalping_desk.service as svc_mod
    from trading_shared.db.session import SessionLocal
    from trading_shared.strategies.scalping_desk.service import ScalpingDeskService

    svc_mod.BACKTEST_CHUNK_DELAY_SEC = float(os.environ.get("BACKTEST_CHUNK_DELAY_SEC", "3.5"))
    svc_mod.BACKTEST_CHUNK_DAYS = int(os.environ.get("BACKTEST_CHUNK_DAYS", "3"))

    db = SessionLocal()
    try:
        svc = ScalpingDeskService(db, user_id, INSTRUMENT_KEY)
        return await svc._load_desk_backtest_candles(
            from_d.isoformat(), to_d.isoformat(), "1m"
        )
    finally:
        db.close()


def aggregate_results(segment_results: list[dict], capital: float) -> dict:
    all_trades: list[dict] = []
    total_bars = 0
    sources: set[str] = set()
    for seg in segment_results:
        all_trades.extend(seg.get("trades") or [])
        total_bars += int(seg.get("bars_loaded") or 0)
        if seg.get("data_source"):
            sources.add(str(seg["data_source"]))

    if not all_trades:
        return {
            "total_trades": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "profit_factor": 0,
            "max_drawdown": 0,
            "final_capital": capital,
            "trades": [],
            "bars_loaded": total_bars,
            "data_source": ",".join(sorted(sources)) or "none",
        }

    wins = [t for t in all_trades if float(t.get("pnl") or 0) > 0]
    losses = [t for t in all_trades if float(t.get("pnl") or 0) < 0]
    total_pnl = round(sum(float(t.get("pnl") or 0) for t in all_trades), 2)
    gross_win = sum(float(t.get("pnl") or 0) for t in wins)
    gross_loss = abs(sum(float(t.get("pnl") or 0) for t in losses))
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_win > 0 else 0)

    equity = capital
    peak = capital
    max_dd = 0.0
    for t in sorted(all_trades, key=lambda x: str(x.get("exit_time") or x.get("entry_time") or "")):
        equity += float(t.get("pnl") or 0)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    monthly: dict[str, dict] = {}
    for t in all_trades:
        ts = str(t.get("exit_time") or t.get("entry_time") or "")[:7]
        if not ts:
            continue
        bucket = monthly.setdefault(ts, {"month": ts, "trades": 0, "pnl": 0.0, "wins": 0})
        bucket["trades"] += 1
        pnl = float(t.get("pnl") or 0)
        bucket["pnl"] = round(bucket["pnl"] + pnl, 2)
        if pnl > 0:
            bucket["wins"] += 1
    monthly_breakdown = []
    for m in sorted(monthly.keys()):
        b = monthly[m]
        monthly_breakdown.append(
            {
                "month": b["month"],
                "trades": b["trades"],
                "pnl": b["pnl"],
                "win_rate": round(b["wins"] / b["trades"] * 100, 1) if b["trades"] else 0,
            }
        )

    return {
        "total_trades": len(all_trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(all_trades) * 100, 2),
        "profit_factor": pf,
        "total_pnl": total_pnl,
        "max_drawdown": round(max_dd, 2),
        "final_capital": round(capital + total_pnl, 2),
        "trades": all_trades,
        "bars_loaded": total_bars,
        "data_source": ",".join(sorted(sources)),
        "monthly_breakdown": monthly_breakdown,
    }


async def run_all(user_id: int, capital: float):
    import trading_shared.strategies.scalping_desk.backtest as bt
    from trading_shared.strategies.scalping_desk.backtest import run_strategy_backtest
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

    bt.MAX_BACKTEST_BARS = int(os.environ.get("MAX_BACKTEST_BARS", "30000"))
    lot = int(INSTRUMENTS[INSTRUMENT_KEY]["lot_size"])
    segs = _segments(BACKTEST_DAYS, SEGMENT_DAYS)
    segment_results: list[dict] = []

    print(f"=== {STRATEGY_CODE} · {BACKTEST_DAYS}d · {len(segs)} segments × {SEGMENT_DAYS}d ===")

    for idx, (from_d, to_d) in enumerate(segs):
        if idx > 0:
            print(f"Pause {SEGMENT_PAUSE_SEC}s (rate-limit spacing)…")
            await asyncio.sleep(SEGMENT_PAUSE_SEC)
        print(f"\nSegment {idx + 1}/{len(segs)}: {from_d} → {to_d}")
        try:
            df, source, notes = await load_segment(user_id, from_d, to_d)
        except Exception as exc:
            print(f"  SKIP load failed: {exc}")
            continue
        if notes:
            print(f"  notes: {'; '.join(notes)}")
        print(f"  bars={len(df):,} source={source}")
        if len(df) < 300:
            print("  SKIP insufficient bars")
            continue

        result = run_strategy_backtest(
            df,
            "1m",
            lot,
            capital,
            strategy_code=STRATEGY_CODE,
            instrument_key=INSTRUMENT_KEY,
            max_loss_per_day=5000,
            max_trades_per_day=3,
        )
        result["data_source"] = source
        result["segment"] = {"from": from_d.isoformat(), "to": to_d.isoformat()}
        segment_results.append(result)
        print(
            f"  trades={result.get('total_trades')} WR={result.get('win_rate')}% "
            f"PnL=₹{result.get('total_pnl')} PF={result.get('profit_factor')}"
        )

    return aggregate_results(segment_results, capital), segment_results


def main() -> int:
    user_id = int(os.environ.get("BACKTEST_USER_ID", "1"))
    capital = float(os.environ.get("BACKTEST_CAPITAL", "100000"))

    agg, segments = asyncio.run(run_all(user_id, capital))

    print("\n=== Aggregated 1-year results ===")
    summary = {
        "strategy": STRATEGY_CODE,
        "instrument": INSTRUMENT_KEY,
        "days_requested": BACKTEST_DAYS,
        "segments_run": len(segments),
        "segments_with_data": len([s for s in segments if (s.get("total_trades") or 0) >= 0]),
        "date_range": {
            "from": (date.today() - timedelta(days=BACKTEST_DAYS)).isoformat(),
            "to": date.today().isoformat(),
        },
        "data_source": agg.get("data_source"),
        "bars_loaded": agg.get("bars_loaded"),
        "total_trades": agg.get("total_trades"),
        "wins": agg.get("wins"),
        "losses": agg.get("losses"),
        "win_rate": agg.get("win_rate"),
        "profit_factor": agg.get("profit_factor"),
        "total_pnl": agg.get("total_pnl"),
        "max_drawdown": agg.get("max_drawdown"),
        "final_capital": agg.get("final_capital"),
        "monthly_breakdown": agg.get("monthly_breakdown"),
    }
    print(json.dumps(summary, indent=2, default=str))

    trades = agg.get("trades") or []
    if trades:
        print(f"\nSample trades (last 5 of {len(trades)}):")
        for t in trades[-5:]:
            print(
                f"  {str(t.get('entry_time', ''))[:16]} {t.get('signal_type')} "
                f"PnL=₹{t.get('pnl')} {t.get('result')}"
            )

    if agg.get("total_trades", 0) == 0:
        print("\nNo trades — Angel history may be rate-limited. Retry after market hours.")
        return 2
    if agg.get("bars_loaded", 0) < BACKTEST_DAYS * 20:
        print("\nWARNING: Low bar count — results are partial, not full 1y coverage.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
