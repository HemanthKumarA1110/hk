#!/usr/bin/env python3
"""Diagnose SCALP-BT-004 trade scarcity on Nifty candles."""
from __future__ import annotations

import pickle
from copy import deepcopy

from trading_shared.strategies.scalping_desk.backtest import run_strategy_backtest
from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS
from trading_shared.strategies.scalping_desk.engine import enrich_candles
from trading_shared.strategies.scalping_desk.orb_breakout_tuning import ORB_BREAKOUT_NIFTY_DEFAULTS

with open("/tmp/bt004_candles.pkl", "rb") as f:
    payload = pickle.load(f)
df = payload["df"]
print("bars", len(df), "range", payload.get("from_date"), payload.get("to_date"))
print("vol_sum", float(df["volume"].sum()) if "volume" in df.columns else -1)
print("close_med", float(df["close"].median()))

en = enrich_candles(df.tail(800).copy())
if "volume_ratio" in en.columns:
    print("vr_desc", {k: float(v) for k, v in en["volume_ratio"].describe().to_dict().items()})
else:
    print("no volume_ratio")

# OR range distribution morning open
from trading_shared.strategies.scalping_desk.battle_tested_scalp import _session_orb, _to_ist

ranges = []
for i in range(40, len(df)):
    ts = df.iloc[i].get("timestamp")
    ist = _to_ist(ts)
    if ist is None:
        continue
    if ist.hour == 9 and ist.minute == 35:
        orb = _session_orb(df.iloc[: i + 1], 15)
        if orb:
            ranges.append(float(orb["high"] - orb["low"]))
print("or_samples", len(ranges))
if ranges:
    import statistics as st

    print(
        "or_stats min/med/mean/p75/max",
        round(min(ranges), 1),
        round(st.median(ranges), 1),
        round(st.mean(ranges), 1),
        round(sorted(ranges)[int(0.75 * len(ranges))], 1),
        round(max(ranges), 1),
    )
    in_40_80 = sum(1 for r in ranges if 40 <= r <= 80)
    print("or_in_40_80", in_40_80, "/", len(ranges))

lot = INSTRUMENTS["nifty50"]["lot_size"]
base = dict(ORB_BREAKOUT_NIFTY_DEFAULTS)
variants = [
    ("baseline", {}),
    ("no_or", {"orb_or_range_min": 0, "orb_or_range_max": 99999, "orb_skip_wide_or": False}),
    ("afternoon", {"orb_entry_cutoff_min": 14 * 60 + 45}),
    (
        "loose",
        {
            "orb_or_range_min": 0,
            "orb_or_range_max": 99999,
            "orb_skip_wide_or": False,
            "orb_entry_cutoff_min": 14 * 60 + 45,
            "orb_vol_min": 0,
            "orb_require_inside_or": False,
            "orb_prior_mode": "off",
            "orb_require_two_bar_momentum": False,
            "orb_rsi_call_min": 40,
            "orb_rsi_call_max": 80,
            "orb_rsi_put_min": 20,
            "orb_rsi_put_max": 60,
        },
    ),
    (
        "or25_120_aft",
        {"orb_or_range_min": 25, "orb_or_range_max": 120, "orb_entry_cutoff_min": 14 * 60 + 45},
    ),
    (
        "or25_120_aft_v1",
        {
            "orb_or_range_min": 25,
            "orb_or_range_max": 120,
            "orb_entry_cutoff_min": 14 * 60 + 45,
            "orb_vol_min": 1.0,
        },
    ),
    (
        "or25_120_aft_v1_off",
        {
            "orb_or_range_min": 25,
            "orb_or_range_max": 120,
            "orb_entry_cutoff_min": 14 * 60 + 45,
            "orb_vol_min": 1.0,
            "orb_require_inside_or": False,
            "orb_prior_mode": "off",
        },
    ),
    (
        "banklike_scale",
        {
            "orb_or_range_min": 20,
            "orb_or_range_max": 150,
            "orb_entry_cutoff_min": 14 * 60 + 45,
            "orb_vol_min": 1.1,
            "orb_buffer_pct": 0.0,
            "orb_require_inside_or": False,
            "orb_prior_mode": "off",
            "orb_require_two_bar_momentum": False,
        },
    ),
]
for name, tw in variants:
    p = deepcopy(base)
    p.update(tw)
    r = run_strategy_backtest(
        df,
        "1m",
        lot,
        100000,
        strategy_code="SCALP-BT-004",
        instrument_key="nifty50",
        params={"orb_breakout": p},
        max_loss_per_day=5000,
        max_trades_per_day=10,
    )
    print(
        f"{name:22} n={r['total_trades']:>3} WR={r['win_rate']:>6} "
        f"PnL={r['total_pnl']:>10} PF={r['profit_factor']}"
    )
    if r.get("trades"):
        t0 = r["trades"][0]
        print("  first", t0.get("entry_time"), t0.get("signal_type"), t0.get("pnl"), t0.get("exit_reason"))
