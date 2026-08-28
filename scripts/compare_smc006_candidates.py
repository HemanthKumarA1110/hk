#!/usr/bin/env python3
"""Focused SCALP-SMC-006 candidates from interrupted OFAT + walk-forward."""

from __future__ import annotations

import json
import os
import pickle
import sys
from copy import deepcopy

sys.path.insert(0, "/app/scripts")
import optimize_scalp_smc006 as opt  # noqa: E402


def main() -> int:
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS
    from trading_shared.strategies.scalping_desk.smc_orb_fvg_tuning import SMC_ORB_FVG_BANK_DEFAULTS

    opt.install_patches()
    lot = int(INSTRUMENTS[opt.INSTRUMENT_KEY]["lot_size"])
    capital = 100000.0
    candles, source, from_date, to_date = opt.get_candles(1)
    train, val, oos = opt.split_wf(candles)
    print(f"bars={len(candles)} {from_date}->{to_date} source={source}", flush=True)

    base = opt.baseline_params()
    # Work set from OFAT winners (manual combine — cascade overwrote momentum earlier)
    refined = deepcopy(base)
    refined.update({
        "smc_orb_entry_cutoff_min": 11 * 60,  # 11:00
        "smc_orb_rsi_put_min": 32,
        "smc_orb_rsi_put_max": 48,
        "smc_orb_rsi_call_min": 50,
        "smc_orb_rsi_call_max": 66,
        "smc_orb_momentum_mode": "one_bar",
        "smc_orb_require_momentum": True,
        "smc_entry_scan_every": 1,
        "smc_min_bars_between": 8,
        "smc_orb_fvg_mode": "or",
        "smc_orb_require_fvg": False,
        "volume_min": 0.0,
        "smc_orb_pad_pct": 0.0008,
        "entry_buffer_pct": 0.10,
        "smc_orb_stop_pts": 50.0,
        "smc_orb_target_pts": 120.0,
        "max_hold_bars": 8,
        "trailing_atr_mult": 0.0,
    })

    candidates = {
        "baseline": deepcopy(base),
        "ofat_scan1_only": {**deepcopy(base), "smc_entry_scan_every": 1},
        "ofat_cutoff_1100": {**deepcopy(base), "smc_orb_entry_cutoff_min": 11 * 60},
        "ofat_put_32_48": {**deepcopy(base), "smc_orb_rsi_put_min": 32, "smc_orb_rsi_put_max": 48},
        "ofat_mom_one_bar": {**deepcopy(base), "smc_orb_momentum_mode": "one_bar", "smc_orb_require_momentum": True},
        "ofat_mom_off": {**deepcopy(base), "smc_orb_momentum_mode": "off", "smc_orb_require_momentum": False},
        "refined_core": deepcopy(refined),
        "refined_scan1_mom_one": deepcopy(refined),
        "refined_scan1_mom_off": {**deepcopy(refined), "smc_orb_momentum_mode": "off", "smc_orb_require_momentum": False},
        "refined_scan2": {**deepcopy(refined), "smc_entry_scan_every": 2},
        "refined_between_5": {**deepcopy(refined), "smc_min_bars_between": 5},
        "refined_hold_6": {**deepcopy(refined), "max_hold_bars": 6},
        "refined_sl45_tg110": {**deepcopy(refined), "smc_orb_stop_pts": 45.0, "smc_orb_target_pts": 110.0},
        "refined_sl55_tg130": {**deepcopy(refined), "smc_orb_stop_pts": 55.0, "smc_orb_target_pts": 130.0},
        "refined_or_90_220": {**deepcopy(refined), "smc_orb_range_min": 90.0, "smc_orb_range_max": 220.0},
        "refined_call_52_68": {**deepcopy(refined), "smc_orb_rsi_call_min": 52, "smc_orb_rsi_call_max": 68},
    }

    rows = []
    for name, params in candidates.items():
        for ds, data in [("train", train), ("val", val), ("oos", oos), ("full", candles)]:
            m = opt.metrics(opt.run_bt(data, lot, capital, params), data if ds != "full" else candles)
            sc = opt.score(m, 7)
            rows.append({"name": name, "dataset": ds, "metrics": m, "score": round(sc, 2), "params": params})
            print(
                f"{name:28} [{ds:5}] tr={m['trades']:>3} WR={m['win_rate']:>5}% PF={m['profit_factor']:>7} "
                f"EXP={m['expectancy']:>8} PnL={m['total_pnl']:>9} DD={m['max_drawdown']:>8} sc={sc:>6.1f}",
                flush=True,
            )

    def oos_ok(name):
        o = next(x for x in rows if x["name"] == name and x["dataset"] == "oos")
        return o["metrics"]["trades"] < 2 or (o["metrics"]["expectancy"] >= 0 and o["metrics"]["win_rate"] >= 50)

    full_rows = [r for r in rows if r["dataset"] == "full"]
    ranked = sorted(
        [r for r in full_rows if r["metrics"]["trades"] >= 8 and r["metrics"]["expectancy"] > 0 and oos_ok(r["name"])],
        key=lambda r: (r["metrics"]["win_rate"], r["score"], r["metrics"]["trades"], r["metrics"]["expectancy"]),
        reverse=True,
    )
    print("\n=== RANKED FULL ===", flush=True)
    for i, r in enumerate(ranked[:10], 1):
        m = r["metrics"]
        print(f"{i:2}. {r['name']:28} WR={m['win_rate']}% PF={m['profit_factor']} EXP={m['expectancy']} tr={m['trades']} PnL={m['total_pnl']} DD={m['max_drawdown']}", flush=True)

    # Prefer configs that also look good on val
    def pick():
        scored = []
        for name in {r["name"] for r in ranked[:8]}:
            tr = next(x for x in rows if x["name"] == name and x["dataset"] == "train")
            va = next(x for x in rows if x["name"] == name and x["dataset"] == "val")
            oo = next(x for x in rows if x["name"] == name and x["dataset"] == "oos")
            fu = next(x for x in rows if x["name"] == name and x["dataset"] == "full")
            ok = (
                fu["metrics"]["win_rate"] >= 70
                and fu["metrics"]["expectancy"] > 0
                and (va["metrics"]["trades"] < 2 or va["metrics"]["expectancy"] >= 0)
                and (oo["metrics"]["trades"] < 2 or oo["metrics"]["expectancy"] >= 0)
            )
            if not ok:
                continue
            scored.append((
                fu["metrics"]["win_rate"],
                fu["score"],
                fu["metrics"]["trades"],
                va["metrics"]["win_rate"] or 0,
                name,
                {"train": tr, "val": va, "oos": oo, "full": fu},
            ))
        scored.sort(reverse=True)
        return scored[0] if scored else None

    chosen = pick()
    report = {
        "strategy": "SCALP-SMC-006",
        "source": source,
        "from": from_date,
        "to": to_date,
        "baseline_defaults_keys": list(SMC_ORB_FVG_BANK_DEFAULTS.keys()),
        "rows": rows,
        "ranked_full": [{"name": r["name"], "metrics": r["metrics"], "score": r["score"]} for r in ranked[:10]],
        "recommended": None if not chosen else {
            "name": chosen[4],
            "params": chosen[5]["full"]["params"],
            "train": chosen[5]["train"]["metrics"],
            "val": chosen[5]["val"]["metrics"],
            "oos": chosen[5]["oos"]["metrics"],
            "full": chosen[5]["full"]["metrics"],
        },
    }
    path = os.environ.get("REPORT_PATH", "/tmp/compare_smc006_candidates.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote {path}", flush=True)
    if chosen:
        print("\n=== RECOMMENDED ===", flush=True)
        print(json.dumps(report["recommended"], indent=2, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
