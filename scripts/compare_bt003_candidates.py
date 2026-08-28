#!/usr/bin/env python3
"""Full-sample comparison of robust SCALP-BT-003 candidates."""

from __future__ import annotations

import importlib.util
import json
import os
from copy import deepcopy

spec = importlib.util.spec_from_file_location("opt", "/app/scripts/optimize_scalp_bt003.py")
opt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(opt)

opt.install_patches()
from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS
import trading_shared.strategies.scalping_desk.backtest as bt

bt.MAX_BACKTEST_BARS = 30000

candles, source, fr, to = opt.get_candles(1)
lot = int(INSTRUMENTS["banknifty"]["lot_size"])
capital = 100000.0
base = opt.baseline_params()
candidates: list[tuple[str, int, int, dict]] = []


def add(name: str, fast: int, slow: int, tweaks: dict) -> None:
    p = deepcopy(base)
    p.update(tweaks)
    candidates.append((name, fast, slow, p))


add("baseline", 9, 21, {})
add("vwap_off", 9, 21, {"ema_require_vwap": False})
add("ema_8_21", 8, 21, {})
add("ema_9_20", 9, 20, {})
add("ema_7_18", 7, 18, {})
add("ema_8_20", 8, 20, {})
add("ema_9_21_lb5", 9, 21, {"ema_cross_lookback": 5})
add("put_35_45", 9, 21, {"ema_rsi_put_min": 35, "ema_rsi_put_max": 45})
add("put_38_46", 9, 21, {"ema_rsi_put_min": 38, "ema_rsi_put_max": 46})
add("call_52_60", 9, 21, {"ema_rsi_call_min": 52, "ema_rsi_call_max": 60})
add("vwap_off_put3545", 9, 21, {"ema_require_vwap": False, "ema_rsi_put_min": 35, "ema_rsi_put_max": 45})
add("vwap_off_ema821", 8, 21, {"ema_require_vwap": False})
add("vwap_off_ema920", 9, 20, {"ema_require_vwap": False})
add("vwap_off_lb5", 9, 21, {"ema_require_vwap": False, "ema_cross_lookback": 5})
add(
    "vwap_off_ema821_put3545",
    8,
    21,
    {"ema_require_vwap": False, "ema_rsi_put_min": 35, "ema_rsi_put_max": 45},
)
add(
    "robust_821_vwapoff_put3846",
    8,
    21,
    {"ema_require_vwap": False, "ema_rsi_put_min": 38, "ema_rsi_put_max": 46},
)
add(
    "auto_core_618",
    6,
    18,
    {
        "ema_cross_lookback": 5,
        "ema_require_vwap": False,
        "ema_rsi_call_min": 52,
        "ema_rsi_call_max": 60,
        "ema_rsi_put_min": 35,
        "ema_rsi_put_max": 45,
        "ema_stop_pts": 60.0,
        "ema_target_pts": 90.0,
    },
)
add(
    "vwap_off_ema821_lb5_put3846",
    8,
    21,
    {
        "ema_require_vwap": False,
        "ema_cross_lookback": 5,
        "ema_rsi_put_min": 38,
        "ema_rsi_put_max": 46,
    },
)

rows = []
for name, f, s, p in candidates:
    opt.set_ema_pair(f, s)
    opt.set_session("both")
    opt.set_allow_expiry(False)
    m = opt.metrics(opt.run_bt(candles, lot, capital, p))
    sc = opt.balanced_score(m, 23)
    rows.append((sc, name, f, s, m, p))
    print(
        f"{name:35} EMA{f}/{s} trades={m['trades']:>3} WR={m['win_rate']:>6}% "
        f"PF={m['profit_factor']:>5} EXP={m['expectancy']:>8} PnL={m['total_pnl']:>10} "
        f"DD={m['max_drawdown']:>9} CWR={m['call_wr']} PWR={m['put_wr']} "
        f"MWR={m['morning_wr']} AWR={m['afternoon_wr']} score={sc:.1f}",
        flush=True,
    )

rows.sort(reverse=True)
print("\nTOP BY SCORE:", flush=True)
for sc, name, f, s, m, _ in rows[:10]:
    print(name, sc, m["win_rate"], m["trades"], m["profit_factor"], m["total_pnl"], m["max_drawdown"], flush=True)

base_wr = 60.87
base_tr = 23
pref = [
    r
    for r in rows
    if r[4]["win_rate"] >= base_wr - 0.01
    and r[4]["trades"] >= base_tr * 0.8
    and r[4]["expectancy"] > 0
    and r[4]["profit_factor"] >= 1.0
]
pref.sort(key=lambda r: (r[4]["win_rate"], r[0], r[4]["trades"]), reverse=True)
print("\nPREF WR-FIRST:", flush=True)
for sc, name, f, s, m, p in pref[:10]:
    print(
        name,
        "WR",
        m["win_rate"],
        "tr",
        m["trades"],
        "PF",
        m["profit_factor"],
        "EXP",
        m["expectancy"],
        "PnL",
        m["total_pnl"],
        "DD",
        m["max_drawdown"],
        flush=True,
    )

# Prefer configs that improve WR OR (same WR with better PF/exp and more trades)
# Avoid EMA 6 (outside tested grid)
pref2 = [r for r in pref if r[2] in (5, 7, 8, 9, 10, 12, 13) or r[1] == "baseline" or "vwap" in r[1]]
if not pref2:
    pref2 = pref
best = pref2[0] if pref2 else rows[0]

# Stability: if vwap_off is close in WR to best and simpler, prefer it
vwap_off = next((r for r in rows if r[1] == "vwap_off"), None)
ema821 = next((r for r in rows if r[1] == "ema_8_21"), None)
robust = next((r for r in rows if r[1] == "robust_821_vwapoff_put3846"), None)

# Manual robust pick: prioritize WR gain with controlled complexity
manual_order = [
    "robust_821_vwapoff_put3846",
    "vwap_off_ema821",
    "vwap_off",
    "ema_8_21",
    "ema_9_20",
    "vwap_off_put3545",
]
chosen = None
for name in manual_order:
    hit = next((r for r in rows if r[1] == name), None)
    if hit and hit[4]["win_rate"] >= base_wr and hit[4]["expectancy"] > 0 and hit[4]["profit_factor"] >= 1.2:
        chosen = hit
        break
if chosen is None:
    chosen = best

print("\nCHOSEN", chosen[1], chosen[2], chosen[3], flush=True)
payload = {
    "name": chosen[1],
    "ema": [chosen[2], chosen[3]],
    "params": chosen[5],
    "metrics": chosen[4],
    "all": [
        {"name": n, "ema": [ff, ss], "metrics": mm, "score": sc}
        for sc, n, ff, ss, mm, _ in rows
    ],
}
print(json.dumps({"name": payload["name"], "ema": payload["ema"], "params": payload["params"], "metrics": payload["metrics"]}, indent=2), flush=True)
with open("/tmp/bt003_final_pick.json", "w", encoding="utf-8") as f:
    json.dump(payload, f, indent=2, default=str)
print("Wrote /tmp/bt003_final_pick.json", flush=True)
