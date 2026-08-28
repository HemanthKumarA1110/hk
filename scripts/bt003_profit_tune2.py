#!/usr/bin/env python3
"""SCALP-BT-003 profit pass 2 — entry unlocks + mild risk, protect WR ~60%+."""

from __future__ import annotations

import json
import os
import pickle
import sys
from copy import deepcopy
from typing import Any

STRATEGY_CODE = "SCALP-BT-003"
INSTRUMENT_KEY = "banknifty"


def baseline() -> dict[str, Any]:
    from trading_shared.strategies.scalping_desk.ema_crossover_tuning import EMA_CROSSOVER_BANK_DEFAULTS

    return dict(EMA_CROSSOVER_BANK_DEFAULTS)


def get_candles():
    for path in (
        os.environ.get("CANDLE_CACHE", "/tmp/bt003_candles.pkl"),
        "/tmp/ad006_candles.pkl",
        "/tmp/smc006_candles.pkl",
    ):
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
    base_full = metrics(run_bt(candles, lot, capital, base))
    base_oos = metrics(run_bt(oos, lot, capital, base))
    print("BASELINE full", json.dumps(base_full), flush=True)
    print("BASELINE oos ", json.dumps(base_oos), flush=True)

    candidates: dict[str, dict] = {"baseline": deepcopy(base)}

    # Wider stop only (tiny lift seen in pass1)
    for stop in [70.0, 75.0, 80.0]:
        p = deepcopy(base)
        p["ema_stop_pts"] = stop
        candidates[f"stop_{int(stop)}"] = p

    # Mild RSI widen (more fills, keep VWAP)
    for call_lo, call_hi, put_lo, put_hi, tag in [
        (52, 62, 35, 45, "call5262"),
        (53, 62, 35, 48, "call5362_put3548"),
        (52, 60, 35, 45, "call5260"),
        (53, 60, 32, 45, "put3245"),
        (53, 60, 38, 46, "put3846"),
        (50, 65, 35, 50, "legacy_rsi"),
    ]:
        p = deepcopy(base)
        p.update(
            {
                "ema_rsi_call_min": call_lo,
                "ema_rsi_call_max": call_hi,
                "ema_rsi_put_min": put_lo,
                "ema_rsi_put_max": put_hi,
            }
        )
        candidates[f"rsi_{tag}"] = p

    # VWAP off variants that previously printed
    for tag, tweaks in [
        ("vwap_off", {"ema_require_vwap": False}),
        ("vwap_off_put3846", {"ema_require_vwap": False, "ema_rsi_put_min": 38, "ema_rsi_put_max": 46}),
        ("vwap_off_stop75", {"ema_require_vwap": False, "ema_stop_pts": 75.0}),
        ("vwap_off_put3846_s75", {"ema_require_vwap": False, "ema_rsi_put_min": 38, "ema_rsi_put_max": 46, "ema_stop_pts": 75.0}),
        ("vwap_off_call5262", {"ema_require_vwap": False, "ema_rsi_call_min": 52, "ema_rsi_call_max": 62}),
        ("vwap_off_mom_off", {"ema_require_vwap": False, "ema_require_two_bar_momentum": False}),
        ("mom_off", {"ema_require_two_bar_momentum": False}),
        ("lookback2", {"ema_cross_lookback": 2}),
        ("lookback4", {"ema_cross_lookback": 4}),
        ("vwap_off_lb2", {"ema_require_vwap": False, "ema_cross_lookback": 2}),
        ("vwap_off_put3846_lb2", {"ema_require_vwap": False, "ema_rsi_put_min": 38, "ema_rsi_put_max": 46, "ema_cross_lookback": 2}),
        # Profit-leaning composite from prior pick + wider stop
        (
            "profit_lean",
            {
                "ema_require_vwap": False,
                "ema_rsi_put_min": 38,
                "ema_rsi_put_max": 46,
                "ema_stop_pts": 75.0,
                "ema_target_pts": 150.0,
                "ema_max_hold_bars": 8,
            },
        ),
        # Keep VWAP, unlock RSI + stop
        (
            "vwap_on_rsi_unlock_s75",
            {
                "ema_rsi_call_min": 52,
                "ema_rsi_call_max": 62,
                "ema_rsi_put_min": 35,
                "ema_rsi_put_max": 48,
                "ema_stop_pts": 75.0,
                "ema_target_pts": 150.0,
            },
        ),
        (
            "vwap_on_rsi_unlock_s70",
            {
                "ema_rsi_call_min": 52,
                "ema_rsi_call_max": 62,
                "ema_rsi_put_min": 38,
                "ema_rsi_put_max": 46,
                "ema_stop_pts": 70.0,
            },
        ),
    ]:
        p = deepcopy(base)
        p.update(tweaks)
        candidates[tag] = p

    rows = []
    for name, params in candidates.items():
        for ds, data in [("train", train), ("val", val), ("oos", oos), ("full", candles)]:
            m = metrics(run_bt(data, lot, capital, params))
            rows.append({"name": name, "dataset": ds, "metrics": m, "params": params})
            print(
                f"{name:30} [{ds:5}] tr={m['trades']:>3} WR={m['win_rate']:>5}% PF={m['profit_factor']:>5} "
                f"EXP={m['expectancy']:>9} PnL={m['total_pnl']:>10} DD={m['max_drawdown']:>9}",
                flush=True,
            )

    def pass_gate(name: str) -> bool:
        fu = next(r for r in rows if r["name"] == name and r["dataset"] == "full")
        va = next(r for r in rows if r["name"] == name and r["dataset"] == "val")
        oo = next(r for r in rows if r["name"] == name and r["dataset"] == "oos")
        m = fu["metrics"]
        if m["trades"] < 12:
            return False
        # Keep WR "good" (>= ~58%) while chasing profit
        if m["win_rate"] < 58.0:
            return False
        if m["total_pnl"] <= base_full["total_pnl"] * 1.15:  # at least +15% PnL
            return False
        if m["expectancy"] <= base_full["expectancy"]:
            return False
        if va["metrics"]["trades"] >= 3 and va["metrics"]["expectancy"] < 0:
            return False
        # OOS: allow mild weakness vs baseline OOS, but not a disaster
        if oo["metrics"]["trades"] >= 4:
            if oo["metrics"]["expectancy"] < min(-800.0, base_oos["expectancy"] - 500):
                return False
            if oo["metrics"]["total_pnl"] < base_oos["total_pnl"] - 15000:
                return False
        return True

    full = [r for r in rows if r["dataset"] == "full" and pass_gate(r["name"])]
    ranked = sorted(
        full,
        key=lambda r: (
            r["metrics"]["total_pnl"],
            r["metrics"]["expectancy"],
            r["metrics"]["win_rate"],
            -r["metrics"]["max_drawdown"],
        ),
        reverse=True,
    )

    print("\n=== RANKED ===", flush=True)
    for i, r in enumerate(ranked[:12], 1):
        m = r["metrics"]
        oo = next(x["metrics"] for x in rows if x["name"] == r["name"] and x["dataset"] == "oos")
        print(
            f"{i:2}. {r['name']:30} WR={m['win_rate']}% PnL={m['total_pnl']} EXP={m['expectancy']} "
            f"PF={m['profit_factor']} tr={m['trades']} DD={m['max_drawdown']} | OOS WR={oo['win_rate']}% PnL={oo['total_pnl']}",
            flush=True,
        )

    # Soft ranking if gate empty: best PnL with WR>=60 and OOS not worse than baseline by 20k
    if not ranked:
        soft = []
        for r in rows:
            if r["dataset"] != "full":
                continue
            m = r["metrics"]
            oo = next(x["metrics"] for x in rows if x["name"] == r["name"] and x["dataset"] == "oos")
            if m["win_rate"] < 60.0:
                continue
            if m["total_pnl"] <= base_full["total_pnl"]:
                continue
            if oo["total_pnl"] < base_oos["total_pnl"] - 20000:
                continue
            soft.append(r)
        ranked = sorted(soft, key=lambda r: (r["metrics"]["total_pnl"], r["metrics"]["win_rate"]), reverse=True)
        print("\n=== SOFT RANKED (WR>=60, PnL>) ===", flush=True)
        for i, r in enumerate(ranked[:12], 1):
            m = r["metrics"]
            oo = next(x["metrics"] for x in rows if x["name"] == r["name"] and x["dataset"] == "oos")
            print(
                f"{i:2}. {r['name']:30} WR={m['win_rate']}% PnL={m['total_pnl']} EXP={m['expectancy']} "
                f"tr={m['trades']} | OOS PnL={oo['total_pnl']} WR={oo['win_rate']}%",
                flush=True,
            )

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
            "baseline_oos": base_oos,
        }

    out = {
        "baseline": base,
        "baseline_full": base_full,
        "baseline_oos": base_oos,
        "ranked": [{"name": r["name"], "metrics": r["metrics"]} for r in ranked[:10]],
        "recommended": recommended,
        "all_full": [
            {"name": r["name"], "metrics": r["metrics"]}
            for r in rows
            if r["dataset"] == "full"
        ],
    }
    path = os.environ.get("REPORT_PATH", "/tmp/bt003_profit_tune2.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nWrote {path}", flush=True)
    if recommended:
        print("\n=== RECOMMENDED ===", flush=True)
        print(json.dumps(recommended, indent=2, default=str), flush=True)
    else:
        print("No recommendation passed gates", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
