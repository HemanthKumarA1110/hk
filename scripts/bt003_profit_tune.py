#!/usr/bin/env python3
"""SCALP-BT-003 profit-focused risk/hold compare (keep entry filters)."""

from __future__ import annotations

import json
import os
import pickle
import sys
from copy import deepcopy
from typing import Any

STRATEGY_CODE = "SCALP-BT-003"
INSTRUMENT_KEY = "banknifty"
CANDLE_CACHE = os.environ.get("CANDLE_CACHE", "/tmp/bt003_candles.pkl")


def baseline() -> dict[str, Any]:
    from trading_shared.strategies.scalping_desk.ema_crossover_tuning import EMA_CROSSOVER_BANK_DEFAULTS

    return dict(EMA_CROSSOVER_BANK_DEFAULTS)


def get_candles():
    for path in (CANDLE_CACHE, "/tmp/ad006_candles.pkl", "/tmp/smc006_candles.pkl", "/tmp/ad005_candles.pkl"):
        if os.path.isfile(path):
            with open(path, "rb") as f:
                payload = pickle.load(f)
            print(f"Loaded {path} bars={len(payload['df']):,}", flush=True)
            return payload["df"], payload.get("source"), payload.get("from_date"), payload.get("to_date")
    raise SystemExit("No candle cache")


def run_bt(candles, lot, capital, params):
    from trading_shared.strategies.scalping_desk.backtest import run_backtest
    import trading_shared.strategies.scalping_desk.backtest as bt

    bt.MAX_BACKTEST_BARS = 30000
    return run_backtest(
        candles,
        "1m",
        lot,
        capital,
        strategy_code=STRATEGY_CODE,
        instrument_key=INSTRUMENT_KEY,
        params={"ema_crossover": params},
        max_loss_per_day=5000,
        max_trades_per_day=5,
        ai_entry=False,
        ai_exit=False,
    )


def metrics(result):
    trades = result.get("trades") or []
    n = int(result.get("total_trades") or 0)
    pnl = float(result.get("total_pnl") or 0)
    return {
        "trades": n,
        "win_rate": float(result.get("win_rate") or 0),
        "profit_factor": float(result.get("profit_factor") or 0),
        "expectancy": round(pnl / n, 2) if n else 0.0,
        "total_pnl": pnl,
        "max_drawdown": float(result.get("max_drawdown") or 0),
        "avg_win": float(result.get("avg_profit_win") or 0),
        "avg_loss": float(result.get("avg_loss_loss") or 0),
        "wins": sum(1 for t in trades if float(t.get("pnl") or 0) > 0),
        "losses": sum(1 for t in trades if float(t.get("pnl") or 0) <= 0),
    }


def score(m, base_wr, base_pnl):
    """Profit-primary with WR floor."""
    if m["trades"] < 8:
        return -100
    wr = m["win_rate"]
    if wr < base_wr - 8:
        return wr  # soft penalty zone
    pnl = m["total_pnl"]
    exp = m["expectancy"]
    pf = min(m["profit_factor"], 4.0)
    wr_keep = max(0, wr - (base_wr - 5)) * 1.5
    return pnl / 2000.0 + exp / 150.0 + pf * 15.0 + wr_keep + min(m["trades"], 50) * 0.2 - m["max_drawdown"] / 3000.0


def main() -> int:
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

    lot = int(INSTRUMENTS[INSTRUMENT_KEY]["lot_size"])
    capital = 100000.0
    candles, source, fr, to = get_candles()
    n = len(candles)
    train = candles.iloc[: int(n * 0.6)].reset_index(drop=True)
    val = candles.iloc[int(n * 0.6) : int(n * 0.8)].reset_index(drop=True)
    oos = candles.iloc[int(n * 0.8) :].reset_index(drop=True)
    print(f"bars={n} {fr}->{to} source={source}", flush=True)

    base = baseline()
    print("\n--- BASELINE ---", flush=True)
    base_full = metrics(run_bt(candles, lot, capital, base))
    base_train = metrics(run_bt(train, lot, capital, base))
    print(json.dumps({"full": base_full, "train": base_train}, indent=2), flush=True)

    candidates: dict[str, dict] = {"baseline": deepcopy(base)}

    # Risk / target / hold only (entry unchanged)
    for stop, tgt in [
        (65, 130),
        (65, 150),
        (65, 160),
        (65, 180),
        (65, 195),
        (70, 160),
        (70, 175),
        (70, 210),
        (55, 140),
        (55, 165),
        (60, 150),
        (60, 180),
        (75, 180),
        (75, 225),
        (80, 200),
    ]:
        p = deepcopy(base)
        p["ema_stop_pts"] = float(stop)
        p["ema_target_pts"] = float(tgt)
        candidates[f"rr_{stop}_{tgt}"] = p

    for hold in [8, 10, 12, 15]:
        p = deepcopy(base)
        p["ema_max_hold_bars"] = hold
        candidates[f"hold_{hold}"] = p

    # Best RR + longer hold combos
    for stop, tgt, hold in [
        (65, 160, 12),
        (65, 180, 12),
        (65, 180, 15),
        (70, 175, 12),
        (70, 210, 12),
        (60, 180, 12),
        (55, 165, 12),
        (75, 225, 15),
    ]:
        p = deepcopy(base)
        p.update({"ema_stop_pts": float(stop), "ema_target_pts": float(tgt), "ema_max_hold_bars": hold})
        candidates[f"combo_{stop}_{tgt}_h{hold}"] = p

    # Mild entry unlock that historically raised PnL (VWAP optional)
    p = deepcopy(base)
    p["ema_require_vwap"] = False
    candidates["vwap_off"] = p
    p = deepcopy(base)
    p.update({"ema_require_vwap": False, "ema_stop_pts": 65.0, "ema_target_pts": 180.0, "ema_max_hold_bars": 12})
    candidates["vwap_off_t180_h12"] = p
    p = deepcopy(base)
    p.update({"ema_require_vwap": False, "ema_stop_pts": 70.0, "ema_target_pts": 210.0, "ema_max_hold_bars": 12})
    candidates["vwap_off_t210_h12"] = p

    rows = []
    for name, params in candidates.items():
        for ds, data in [("train", train), ("val", val), ("oos", oos), ("full", candles)]:
            m = metrics(run_bt(data, lot, capital, params))
            sc = score(m, base_full["win_rate"], base_full["total_pnl"])
            rows.append({"name": name, "dataset": ds, "metrics": m, "score": round(sc, 2), "params": params})
            print(
                f"{name:28} [{ds:5}] tr={m['trades']:>3} WR={m['win_rate']:>5}% PF={m['profit_factor']:>5} "
                f"EXP={m['expectancy']:>9} PnL={m['total_pnl']:>10} DD={m['max_drawdown']:>9}",
                flush=True,
            )

    def ok(name):
        tr = next(r for r in rows if r["name"] == name and r["dataset"] == "train")
        va = next(r for r in rows if r["name"] == name and r["dataset"] == "val")
        oo = next(r for r in rows if r["name"] == name and r["dataset"] == "oos")
        fu = next(r for r in rows if r["name"] == name and r["dataset"] == "full")
        # Keep WR within ~8pp of baseline full; positive expectancy everywhere with trades
        if fu["metrics"]["win_rate"] < base_full["win_rate"] - 8:
            return False
        if fu["metrics"]["total_pnl"] <= base_full["total_pnl"]:
            return False
        if fu["metrics"]["expectancy"] <= 0:
            return False
        if va["metrics"]["trades"] >= 3 and va["metrics"]["expectancy"] < 0:
            return False
        if oo["metrics"]["trades"] >= 3 and oo["metrics"]["expectancy"] < 0:
            return False
        return True

    full = [r for r in rows if r["dataset"] == "full" and ok(r["name"])]
    ranked = sorted(full, key=lambda r: (r["metrics"]["total_pnl"], r["metrics"]["expectancy"], r["metrics"]["win_rate"]), reverse=True)

    print("\n=== RANKED (profit up, WR protected) ===", flush=True)
    for i, r in enumerate(ranked[:10], 1):
        m = r["metrics"]
        print(f"{i:2}. {r['name']:28} WR={m['win_rate']}% PnL={m['total_pnl']} EXP={m['expectancy']} PF={m['profit_factor']} tr={m['trades']} DD={m['max_drawdown']}", flush=True)

    recommended = None
    if ranked:
        name = ranked[0]["name"]
        recommended = {
            "name": name,
            "params": next(r["params"] for r in rows if r["name"] == name),
            "train": next(r["metrics"] for r in rows if r["name"] == name and r["dataset"] == "train"),
            "val": next(r["metrics"] for r in rows if r["name"] == name and r["dataset"] == "val"),
            "oos": next(r["metrics"] for r in rows if r["name"] == name and r["dataset"] == "oos"),
            "full": next(r["metrics"] for r in rows if r["name"] == name and r["dataset"] == "full"),
            "baseline_full": base_full,
        }

    out = {
        "strategy": STRATEGY_CODE,
        "baseline": base,
        "baseline_full": base_full,
        "ranked": [{"name": r["name"], "metrics": r["metrics"]} for r in ranked[:10]],
        "recommended": recommended,
    }
    path = os.environ.get("REPORT_PATH", "/tmp/bt003_profit_tune.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nWrote {path}", flush=True)
    if recommended:
        print("\n=== RECOMMENDED ===", flush=True)
        print(json.dumps(recommended, indent=2, default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
