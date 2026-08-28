#!/usr/bin/env python3
"""Validate robust SCALP-BT-004 candidates (reject overfit B_locked)."""
from __future__ import annotations

import json
import pickle
from copy import deepcopy

from trading_shared.strategies.scalping_desk.backtest import run_strategy_backtest
from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS
from trading_shared.strategies.scalping_desk.orb_breakout_tuning import ORB_BREAKOUT_NIFTY_DEFAULTS

with open("/tmp/bt004_candles.pkl", "rb") as f:
    payload = pickle.load(f)
df = payload["df"]
spot = float(df["close"].median())
lot = int(INSTRUMENTS["nifty50"]["lot_size"])
n = len(df)
train, val, oos = df.iloc[: int(n * 0.6)], df.iloc[int(n * 0.6) : int(n * 0.8)], df.iloc[int(n * 0.8) :]


def pts(p):
    return p / spot


def run(orb, frame):
    r = run_strategy_backtest(
        frame.reset_index(drop=True),
        "1m",
        lot,
        100000,
        strategy_code="SCALP-BT-004",
        instrument_key="nifty50",
        params={"orb_breakout": orb},
        max_loss_per_day=5000,
        max_trades_per_day=5,
    )
    trades = r.get("trades") or []
    pnl = float(r["total_pnl"])
    nt = int(r["total_trades"])
    return {
        "trades": nt,
        "win_rate": float(r["win_rate"]),
        "profit_factor": float(r["profit_factor"]),
        "expectancy": round(pnl / nt, 2) if nt else 0.0,
        "total_pnl": pnl,
        "max_drawdown": float(r["max_drawdown"]),
        "avg_win": float(r.get("avg_profit_win") or 0),
        "avg_loss": float(r.get("avg_loss_loss") or 0),
        "call_n": sum(1 for t in trades if str(t.get("signal_type")).upper() == "CALL"),
        "put_n": sum(1 for t in trades if str(t.get("signal_type")).upper() == "PUT"),
    }


base = dict(ORB_BREAKOUT_NIFTY_DEFAULTS)
scaffold = deepcopy(base)
scaffold.update(
    {
        "orb_entry_cutoff_min": 885,
        "orb_prior_mode": "off",
        "orb_require_inside_or": False,
        "orb_or_range_min": 40.0,
        "orb_or_range_max": 80.0,
        "orb_skip_wide_or": True,
        "orb_vol_min": 1.15,
        "orb_require_two_bar_momentum": False,
        "orb_momentum_mode": "two_bar",
        "orb_momentum_atr_mult": 0.0,
        "orb_rsi_call_min": 52,
        "orb_rsi_call_max": 66,
        "orb_rsi_put_min": 32,
        "orb_rsi_put_max": 46,
        "orb_ema_fast": 8,
        "orb_ema_slow": 20,
        "orb_buffer_pct": pts(2),
        "orb_stop_pts": 6.0,
        "orb_target_pts": 12.0,
        "orb_max_hold_bars": 10,
        "orb_min_separation_pct": 0.0,
        "orb_min_body_pct": 0.0,
        "orb_require_vwap": False,
        "orb_require_rsi_slope": False,
        "orb_vol_lookback": 0,
    }
)

candidates = {}
candidates["baseline"] = base
candidates["scaffold"] = scaffold

c = deepcopy(scaffold)
c.update({"orb_buffer_pct": pts(4)})
candidates["buf4"] = c

c = deepcopy(scaffold)
c.update({"orb_or_range_min": 45.0, "orb_target_pts": 14.0})
candidates["or45_tp14"] = c

c = deepcopy(scaffold)
c.update({"orb_require_two_bar_momentum": True, "orb_momentum_mode": "atr", "orb_momentum_atr_mult": 0.25})
candidates["atr025"] = c

c = deepcopy(scaffold)
c.update({"orb_vol_min": 1.35})
candidates["vol135"] = c

c = deepcopy(scaffold)
c.update({"orb_or_range_min": 45.0, "orb_buffer_pct": pts(4), "orb_vol_min": 1.25})
candidates["or45_buf4_vol125"] = c

c = deepcopy(scaffold)
c.update({
    "orb_or_range_min": 45.0,
    "orb_buffer_pct": pts(4),
    "orb_require_two_bar_momentum": True,
    "orb_momentum_mode": "atr",
    "orb_momentum_atr_mult": 0.25,
    "orb_vol_min": 1.15,
})
candidates["or45_buf4_atr"] = c

c = deepcopy(scaffold)
c.update({"orb_or_range_min": 45.0, "orb_vol_min": 1.35, "orb_buffer_pct": pts(4)})
candidates["or45_vol135_buf4"] = c

c = deepcopy(scaffold)
c.update({
    "orb_or_range_min": 45.0,
    "orb_buffer_pct": pts(4),
    "orb_vol_min": 1.20,
    "orb_stop_pts": 6.0,
    "orb_target_pts": 12.0,
    "orb_require_two_bar_momentum": True,
    "orb_momentum_mode": "two_bar",
})
candidates["or45_buf4_vol120_mom"] = c

c = deepcopy(scaffold)
c.update({"orb_entry_cutoff_min": 630})
candidates["morning_scaffold"] = c

c = deepcopy(candidates["atr025"])
c["orb_buffer_pct"] = pts(3)
candidates["atr025_buf3"] = c
c = deepcopy(candidates["atr025"])
c["orb_vol_min"] = 1.20
candidates["atr025_vol120"] = c
c = deepcopy(candidates["atr025"])
c.update({"orb_or_range_min": 45.0, "orb_target_pts": 14.0})
candidates["atr025_or45_tp14"] = c

# Concept retention: keep 2-bar mom ON but with other unlocks
c = deepcopy(scaffold)
c.update({
    "orb_require_two_bar_momentum": True,
    "orb_momentum_mode": "two_bar",
    "orb_or_range_min": 40.0,
    "orb_buffer_pct": pts(4),
    "orb_vol_min": 1.20,
})
candidates["concept_mom_buf4_vol120"] = c

results = {}
for name, orb in candidates.items():
    print(f"\n=== {name} ===", flush=True)
    row = {
        "params": orb,
        "train": run(orb, train),
        "val": run(orb, val),
        "oos": run(orb, oos),
        "full": run(orb, df),
    }
    results[name] = row
    for split in ("train", "val", "oos", "full"):
        m = row[split]
        print(
            f"  {split:5} n={m['trades']:>3} WR={m['win_rate']:>6}% PF={m['profit_factor']:>5} "
            f"EXP={m['expectancy']:>8} PnL={m['total_pnl']:>9} DD={m['max_drawdown']:>8}",
            flush=True,
        )


def robust_score(row):
    tr, va, oo, fu = row["train"], row["val"], row["oos"], row["full"]
    if fu["trades"] < 8:
        return -1000
    if tr["expectancy"] <= 0:
        return -500
    overfit = 0
    if tr["trades"] <= 7 and tr["win_rate"] >= 95:
        overfit -= 80
    if va["trades"] >= 3 and va["expectancy"] < 0:
        overfit -= 40
    if va["trades"] >= 3 and va["win_rate"] < 40:
        overfit -= 20
    oos_pen = 0
    if oo["trades"] >= 3 and oo["expectancy"] < 0:
        oos_pen -= 30
    if oo["trades"] == 0:
        oos_pen -= 5
    wr = fu["win_rate"]
    pf = min(fu["profit_factor"], 5)
    exp = fu["expectancy"]
    n = fu["trades"]
    dd = fu["max_drawdown"]
    val_bonus = 0
    if va["trades"] >= 3 and va["expectancy"] > 0:
        val_bonus += 25 + min(va["win_rate"], 80) * 0.3
    return wr * 2.0 + pf * 15 + min(exp / 200, 20) + min(n, 25) * 1.5 + val_bonus + overfit + oos_pen - min(dd / 1000, 25)


ranked = sorted(results.items(), key=lambda kv: robust_score(kv[1]), reverse=True)
print("\n=== ROBUST RANK ===", flush=True)
for i, (name, row) in enumerate(ranked, 1):
    print(
        f"{i:2}. {name:28} score={robust_score(row):.1f} "
        f"fullWR={row['full']['win_rate']} n={row['full']['trades']} valEXP={row['val']['expectancy']}",
        flush=True,
    )

best_name, best = ranked[0]
out = {
    "recommended_name": best_name,
    "recommended_params": best["params"],
    "metrics": {k: best[k] for k in ("train", "val", "oos", "full")},
    "baseline_full": results["baseline"]["full"],
    "ranked": [{"name": n, "score": round(robust_score(r), 2), **{s: r[s] for s in ("train", "val", "oos", "full")}} for n, r in ranked],
    "spot_ref": spot,
}
with open("/tmp/bt004_robust_pick.json", "w") as f:
    json.dump(out, f, indent=2, default=str)
print("\nPICK", best_name, flush=True)
print(json.dumps(best["params"], indent=2, default=str), flush=True)
print(json.dumps(best["full"], indent=2), flush=True)
