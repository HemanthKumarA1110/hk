#!/usr/bin/env python3
"""Focused SCALP-AD-006 candidate comparison after OFAT (correct risk mults)."""

from __future__ import annotations

import json
import os
import pickle
import sys
from copy import deepcopy

# Reuse optimize script patches
sys.path.insert(0, "/app/scripts")
import optimize_scalp_ad006 as opt  # noqa: E402


def main() -> int:
    import trading_shared.strategies.scalping_desk.backtest as bt
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

    bt.MAX_BACKTEST_BARS = 30000
    opt.install_patches()
    lot = int(INSTRUMENTS[opt.INSTRUMENT_KEY]["lot_size"])
    capital = 100000.0

    candles, source, from_date, to_date = opt.get_candles(1)
    train, val, oos = opt.split_wf(candles)
    print(f"bars={len(candles)} {from_date}->{to_date} source={source}", flush=True)

    entry = {
        "vb_near_atr_mult": 0.0,
        "vb_near_pct": 0.25,
        "vb_call_prev_rsi_max": 43,
        "vb_call_rsi_min": 43,
        "vb_call_rsi_max": 55,
        "vb_put_prev_rsi_min": 54,
        "vb_put_rsi_min": 44,
        "vb_put_rsi_max": 58,
        "vb_rsi_turn_min": 0.0,
        "vb_candle_mode": "off",
        "vb_multi_bar": 1,
        "vb_side_mode": "touch",
        "vb_side_displace_atr": 0.05,
        "vb_stop_atr_mult": 1.14,
        "vb_stop_floor_pct": 0.0002,
        "vb_target_atr_mult": 0.225,
        "vb_min_target_pts": 10.0,
        "vb_max_hold_bars": 3,
        "vb_require_regime": False,
    }

    candidates: dict[str, dict] = {
        "baseline_code": opt.baseline_params(),
        "ofat_rec_raw": {
            **entry,
            "vb_stop_atr_mult": 0.6,
            "vb_target_atr_mult": 0.3,
            "vb_max_hold_bars": 3,
            "vb_candle_mode": "off",
        },
        "entry_hold3_risk_code": deepcopy(entry),
        "entry_hold3_risk_doc": {**entry, "vb_stop_atr_mult": 1.2, "vb_target_atr_mult": 0.5, "vb_max_hold_bars": 3},
        "entry_hold6_risk_code": {**entry, "vb_max_hold_bars": 6},
        "entry_hold8_risk_doc": {**entry, "vb_stop_atr_mult": 1.2, "vb_target_atr_mult": 0.5, "vb_max_hold_bars": 8},
        "entry_candle_color": {**entry, "vb_candle_mode": "color"},
        "entry_candle_body40": {**entry, "vb_candle_mode": "body40"},
        "near_atr_0.40": {**entry, "vb_near_atr_mult": 0.40, "vb_near_pct": 0.0},
        "near_atr_0.50": {**entry, "vb_near_atr_mult": 0.50, "vb_near_pct": 0.0},
        "near_atr_0.60": {**entry, "vb_near_atr_mult": 0.60, "vb_near_pct": 0.0},
        "near_pct_0.20": {**entry, "vb_near_pct": 0.20},
        "near_pct_0.25": deepcopy(entry),
        "near_pct_0.30": {**entry, "vb_near_pct": 0.30},
        "sl_0.8_tg_0.4": {**entry, "vb_stop_atr_mult": 0.8, "vb_target_atr_mult": 0.4},
        "sl_1.0_tg_0.5": {**entry, "vb_stop_atr_mult": 1.0, "vb_target_atr_mult": 0.5},
        "sl_1.14_tg_0.225": deepcopy(entry),
        "sl_1.2_tg_0.5": {**entry, "vb_stop_atr_mult": 1.2, "vb_target_atr_mult": 0.5},
        "sl_1.4_tg_0.7": {**entry, "vb_stop_atr_mult": 1.4, "vb_target_atr_mult": 0.7},
        "morning_only": deepcopy(entry),
        "ranging_lowvol": deepcopy(entry),
        "put_cur_42_55": {**entry, "vb_put_rsi_min": 42, "vb_put_rsi_max": 55},
        "call_prev_45_keep": {**entry, "vb_call_prev_rsi_max": 45, "vb_call_rsi_min": 45, "vb_call_rsi_max": 58},
    }

    rows = []
    for name, params in candidates.items():
        regimes = None
        session = "both"
        if name == "morning_only":
            session = "morning"
        if name == "ranging_lowvol":
            regimes = {"ranging", "RANGING", "low_volatility", "LOW_VOLATILITY"}
        opt.set_cfg(params, session=session, regimes=regimes)
        for ds, data in [("train", train), ("val", val), ("oos", oos), ("full", candles)]:
            m = opt.metrics(opt.run_bt(data, lot, capital), data if ds != "full" else candles)
            sc = opt.balanced_score(m, 15)
            rows.append({"name": name, "dataset": ds, "metrics": m, "score": round(sc, 2), "params": params})
            print(
                f"{name:28} [{ds:5}] tr={m['trades']:>3} WR={m['win_rate']:>5}% PF={m['profit_factor']:>6} "
                f"EXP={m['expectancy']:>8} PnL={m['total_pnl']:>9} DD={m['max_drawdown']:>8}",
                flush=True,
            )

    # Prefer full-sample positive expectancy, good WR, enough trades; require OOS expectancy >= 0 if trades>=3
    full_rows = [r for r in rows if r["dataset"] == "full"]
    by_name = {r["name"]: r for r in full_rows}

    def oos_ok(name):
        o = next(x for x in rows if x["name"] == name and x["dataset"] == "oos")
        return o["metrics"]["trades"] < 3 or o["metrics"]["expectancy"] >= 0

    ranked = sorted(
        [r for r in full_rows if r["metrics"]["trades"] >= 8 and r["metrics"]["expectancy"] > 0 and oos_ok(r["name"])],
        key=lambda r: (r["metrics"]["win_rate"], r["metrics"]["profit_factor"], r["metrics"]["expectancy"], r["metrics"]["trades"]),
        reverse=True,
    )
    print("\n=== RANKED FULL (WR primary) ===", flush=True)
    for i, r in enumerate(ranked[:12], 1):
        m = r["metrics"]
        print(f"{i:2}. {r['name']:28} WR={m['win_rate']}% PF={m['profit_factor']} EXP={m['expectancy']} tr={m['trades']} PnL={m['total_pnl']} DD={m['max_drawdown']}", flush=True)

    out = {"source": source, "from": from_date, "to": to_date, "rows": rows, "ranked_full": ranked[:12]}
    path = os.environ.get("REPORT_PATH", "/tmp/compare_ad006_candidates.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"Wrote {path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
