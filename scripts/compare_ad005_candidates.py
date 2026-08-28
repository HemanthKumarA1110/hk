#!/usr/bin/env python3
import importlib.util
import json
from copy import deepcopy

spec = importlib.util.spec_from_file_location("opt", "/app/scripts/optimize_scalp_ad005.py")
opt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(opt)
opt.install_patches()

from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS
import trading_shared.strategies.scalping_desk.backtest as bt

bt.MAX_BACKTEST_BARS = 30000
c, *_ = opt.get_candles(1)
train, val, oos = opt.split_wf(c)
lot = int(INSTRUMENTS["banknifty"]["lot_size"])
base = opt.baseline_params()

# Viable entry core from optimization diagnosis
work = deepcopy(base)
work.update({
    "mb_vwap_distance_pct": 1.0,
    "mb_require_supertrend": False,
    "mb_require_two_bar_momentum": False,
    "mb_momentum_mode": "off",
    "mb_ema_sep_pct": 0.0,
})

candidates = []

def add(name, tweaks):
    p = deepcopy(work)
    p.update(tweaks)
    candidates.append((name, p))

add("entry_only", {})
add("hold_5", {"mb_max_hold_bars": 5})
add("hold_6", {"mb_max_hold_bars": 6})
add("hold_7", {"mb_max_hold_bars": 7})
add("hold_7_call5064", {"mb_max_hold_bars": 7, "mb_rsi_call_min": 50, "mb_rsi_call_max": 64})
add("hold_5_ema_cross", {"mb_max_hold_bars": 5, "mb_ema_mode": "cross"})
add("hold_7_ema_cross", {"mb_max_hold_bars": 7, "mb_ema_mode": "cross"})
add("hold_7_sep004", {"mb_max_hold_bars": 7, "mb_ema_sep_pct": 0.04})
add("hold_7_vol115", {"mb_max_hold_bars": 7, "mb_index_volume_spike_ratio": 1.15})
add("hold_7_tgt07", {"mb_max_hold_bars": 7, "mb_target_atr_mult": 0.70})
add("hold_7_sl10_tgt07", {"mb_max_hold_bars": 7, "mb_stop_atr_mult": 1.0, "mb_target_atr_mult": 0.70})
add("auto_rec", {
    "mb_ema_sep_pct": 0.0,
    "mb_vwap_distance_pct": 1.0,
    "mb_require_supertrend": False,
    "mb_momentum_mode": "off",
    "mb_require_two_bar_momentum": False,
})

rows = []
for name, p in candidates:
    opt.set_cfg(p)
    full = opt.metrics(opt.run_bt(c, lot, 100000), c)
    o = opt.metrics(opt.run_bt(oos, lot, 100000), oos)
    t = opt.metrics(opt.run_bt(train, lot, 100000), train)
    sc = opt.balanced_score(full, 15)
    rows.append((sc, name, p, full, o, t))
    print(
        f"{name:22} FULL tr={full['trades']:>3} WR={full['win_rate']:>6} PF={full['profit_factor']:>5} "
        f"EXP={full['expectancy']:>8} PnL={full['total_pnl']:>9} DD={full['max_drawdown']:>8} | "
        f"OOS tr={o['trades']:>3} WR={o['win_rate']:>6} PF={o['profit_factor']:>5} EXP={o['expectancy']:>8} | "
        f"TRAIN WR={t['win_rate']}",
        flush=True,
    )

# Prefer full WR with PF>=1.2, exp>0, trades>=12, then score
pref = [r for r in rows if r[3]["win_rate"] >= 55 and r[3]["profit_factor"] >= 1.2 and r[3]["expectancy"] > 0 and r[3]["trades"] >= 12]
pref.sort(key=lambda r: (r[3]["win_rate"], r[0], r[3]["trades"]), reverse=True)
print("\nPREF:", flush=True)
for sc, name, p, full, o, t in pref[:8]:
    print(name, "WR", full["win_rate"], "tr", full["trades"], "PF", full["profit_factor"], "OOS_WR", o["win_rate"], flush=True)

chosen = pref[0] if pref else max(rows, key=lambda r: r[0])
print("\nCHOSEN", chosen[1], flush=True)
print(json.dumps({"name": chosen[1], "params": chosen[2], "full": chosen[3], "oos": chosen[4], "train": chosen[5]}, indent=2), flush=True)
with open("/tmp/ad005_final_pick.json", "w") as f:
    json.dump({"name": chosen[1], "params": chosen[2], "full": chosen[3], "oos": chosen[4], "train": chosen[5]}, f, indent=2, default=str)
