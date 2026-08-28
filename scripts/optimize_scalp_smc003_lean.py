#!/usr/bin/env python3
"""Lean OFAT for SCALP-SMC-003 — Nifty SMC ORB+FVG.

Baseline already ~100% WR / tiny expectancy. Optimize for expectancy + PnL
while keeping high WR and sufficient trades. Train-only OFAT, then val/OOS.

    PYTHONUNBUFFERED=1 python /app/scripts/optimize_scalp_smc003_lean.py
"""

from __future__ import annotations

import json
import os
import pickle
import sys
import time
from copy import deepcopy
from itertools import product
from typing import Any

STRATEGY_ID = "smc_orb_fvg"
STRATEGY_CODE = "SCALP-SMC-003"
INSTRUMENT_KEY = "nifty50"
MIN_TRADES = int(os.environ.get("MIN_TRADES", "5"))
CANDLE_CACHE = os.environ.get("CANDLE_CACHE", "/tmp/bt004_candles.pkl")


def baseline_params() -> dict[str, Any]:
    from trading_shared.strategies.scalping_desk.smc_orb_fvg_tuning import SMC_ORB_FVG_NIFTY_LEGACY

    return dict(SMC_ORB_FVG_NIFTY_LEGACY)


def get_candles():
    with open(CANDLE_CACHE, "rb") as f:
        p = pickle.load(f)
    return p["df"], p["source"], p["from_date"], p["to_date"]


def run_bt(candles, lot, capital, params):
    from trading_shared.strategies.scalping_desk.smc_backtest import run_single_smc_backtest

    return run_single_smc_backtest(
        candles,
        STRATEGY_ID,
        lot,
        capital,
        instrument_key=INSTRUMENT_KEY,
        params=params,
        max_lots_per_trade=2,
        max_loss_per_day=5000,
        max_trades_per_day=5,
    )


def streaks(trades):
    mw = ml = cw = cl = 0
    for t in trades:
        if float(t.get("pnl") or 0) > 0:
            cw += 1
            cl = 0
            mw = max(mw, cw)
        else:
            cl += 1
            cw = 0
            ml = max(ml, cl)
    return mw, ml


def subset(rows):
    if not rows:
        return {"n": 0, "wr": None, "pnl": 0.0, "pf": None, "exp": None, "dd": 0.0}
    wins = [t for t in rows if float(t.get("pnl") or 0) > 0]
    losses = [t for t in rows if float(t.get("pnl") or 0) <= 0]
    pnl = sum(float(t.get("pnl") or 0) for t in rows)
    gp = sum(float(t.get("pnl") or 0) for t in wins)
    gl = abs(sum(float(t.get("pnl") or 0) for t in losses))
    eq = peak = dd = 0.0
    for t in rows:
        eq += float(t.get("pnl") or 0)
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "n": len(rows),
        "wr": round(len(wins) / len(rows) * 100, 2),
        "pnl": round(pnl, 2),
        "pf": round(gp / gl, 2) if gl else (round(gp, 2) if gp else 0.0),
        "exp": round(pnl / len(rows), 2),
        "dd": round(dd, 2),
        "wins": len(wins),
        "losses": len(losses),
    }


def metrics(res, candles=None):
    trades = res.get("trades") or []
    n = int(res.get("total_trades") or 0)
    pnl = float(res.get("total_pnl") or 0)
    calls = [t for t in trades if str(t.get("signal_type")).upper() == "CALL"]
    puts = [t for t in trades if str(t.get("signal_type")).upper() == "PUT"]
    mw, ml = streaks(trades)
    wins = [t for t in trades if float(t.get("pnl") or 0) > 0]
    losses = [t for t in trades if float(t.get("pnl") or 0) <= 0]
    fvg_entries, mom_entries = [], []
    for t in trades:
        conds = " ".join(str(c) for c in (t.get("conditions") or []))
        ind = t.get("indicators") or {}
        if isinstance(ind, dict):
            conds += " " + " ".join(str(c) for c in (ind.get("conditions") or []))
        cl = conds.lower()
        if "fvg" in cl:
            fvg_entries.append(t)
        elif "momentum" in cl:
            mom_entries.append(t)
    regimes: dict[str, list] = {}
    if candles is not None and trades and "timestamp" in candles.columns:
        try:
            from trading_shared.strategies.scalping_desk.market_context import detect_regime_from_candles

            ts_col = candles["timestamp"].astype(str)
            for t in trades:
                et = str(t.get("entry_time") or "")
                matches = ts_col[ts_col.str.startswith(et[:16])].index
                if not len(matches):
                    continue
                idx = int(matches[0])
                try:
                    reg = str(detect_regime_from_candles(candles.iloc[max(0, idx - 60) : idx + 1]).value)
                except Exception:
                    reg = "UNKNOWN"
                regimes.setdefault(reg, []).append(t)
        except Exception:
            pass
    return {
        "trades": n,
        "win_rate": float(res.get("win_rate") or 0),
        "profit_factor": float(res.get("profit_factor") or 0),
        "expectancy": round(pnl / n, 2) if n else 0.0,
        "total_pnl": pnl,
        "max_drawdown": float(res.get("max_drawdown") or 0),
        "avg_win": float(res.get("avg_profit_win") or 0),
        "avg_loss": float(res.get("avg_loss_loss") or 0),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "max_consec_wins": mw,
        "max_consec_losses": ml,
        "call_n": len(calls),
        "call_wr": subset(calls)["wr"],
        "put_n": len(puts),
        "put_wr": subset(puts)["wr"],
        "session_detail": {"CALL": subset(calls), "PUT": subset(puts), "FVG": subset(fvg_entries), "MOMENTUM": subset(mom_entries)},
        "regimes": {k: subset(v) for k, v in regimes.items()},
    }


def score(m, ref_n=20):
    """WR-primary but heavily reward expectancy/PnL when WR already near ceiling."""
    n = m["trades"]
    wr = float(m["win_rate"])
    pf = min(float(m["profit_factor"] or 0), 5.0)
    exp = float(m["expectancy"] or 0)
    pnl = float(m["total_pnl"] or 0)
    dd = float(m["max_drawdown"] or 0)
    if n < MIN_TRADES:
        return -100.0 + n + wr * 0.05
    if exp <= 0:
        return wr * 0.5 + pf - 40
    trade_sc = max(0.0, min(n / max(ref_n, 1), 2.5)) * 10
    # When WR is already high, differentiate on expectancy/PnL.
    wr_term = wr * (1.2 if wr < 95 else 0.6)
    return wr_term + pf * 8 + max(min(exp / 40.0, 30), -10) + trade_sc + max(min(pnl / 800.0, 25), -10) - min(dd / 400.0, 25)


def split_wf(df):
    n = len(df)
    return (
        df.iloc[: int(n * 0.6)].reset_index(drop=True),
        df.iloc[int(n * 0.6) : int(n * 0.8)].reset_index(drop=True),
        df.iloc[int(n * 0.8) :].reset_index(drop=True),
    )


def main() -> int:
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

    lot = int(INSTRUMENTS[INSTRUMENT_KEY]["lot_size"])
    capital = 100000.0
    df, source, fr, to = get_candles()
    train, val, oos = split_wf(df)
    base = baseline_params()
    print(f"=== {STRATEGY_CODE} LEAN bars={len(df)} {fr}→{to} WF={len(train)}/{len(val)}/{len(oos)} ===", flush=True)

    t0 = time.time()
    base_full = metrics(run_bt(df, lot, capital, base), df)
    base_train = metrics(run_bt(train, lot, capital, base), train)
    base_val = metrics(run_bt(val, lot, capital, base), val)
    base_oos = metrics(run_bt(oos, lot, capital, base), oos)
    print("BASELINE", json.dumps({"full": base_full, "train": base_train, "val": base_val, "oos": base_oos}, indent=2, default=str), flush=True)

    rows = []
    work = deepcopy(base)
    ref_n = max(base_train["trades"], 12)

    def ev(label, group, params, dataset="train"):
        data = {"train": train, "val": val, "oos": oos, "full": df}[dataset]
        m = metrics(run_bt(data, lot, capital, params), data)
        sc = score(m, ref_n)
        row = {"label": label, "group": group, "dataset": dataset, "params": dict(params), "metrics": m, "score": round(sc, 2)}
        rows.append(row)
        print(
            f"{group:10} {label:28} [{dataset}] n={m['trades']:>3} WR={m['win_rate']:>6}% "
            f"PF={m['profit_factor']:>7} EXP={m['expectancy']:>8} PnL={m['total_pnl']:>9} DD={m['max_drawdown']:>7} sc={sc:>6.1f}",
            flush=True,
        )
        return row

    def best(group):
        g = [r for r in rows if r["group"] == group and r["dataset"] == "train" and r["metrics"]["trades"] >= MIN_TRADES]
        pos = [r for r in g if r["metrics"]["expectancy"] > 0]
        pool = pos or g
        if not pool:
            return None
        return max(pool, key=lambda r: (r["score"], r["metrics"]["expectancy"], r["metrics"]["win_rate"]))

    def lock(group, *keys):
        b = best(group)
        if not b:
            return
        for k in keys:
            if k in b["params"]:
                work[k] = b["params"][k]
        print("LOCK", group, {k: work.get(k) for k in keys}, flush=True)

    # 1 FVG gap — code units gap/mid*100
    print("\n--- 1 FVG gap ---", flush=True)
    for g in [0.008, 0.05, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.80, 1.00, 1.20, 1.50]:
        p = deepcopy(work); p["fvg_min_gap_pct"] = float(g); ev(f"gap_{g}", "fvg_gap", p)
    lock("fvg_gap", "fvg_min_gap_pct")

    # 2 path
    print("\n--- 2 Path ---", flush=True)
    for mode, flags in [
        ("fvg_or_mom", {"smc_orb_path_mode": "fvg_or_mom", "smc_orb_require_fvg": False, "smc_orb_require_ema_momentum": False}),
        ("fvg_only", {"smc_orb_path_mode": "fvg_only", "smc_orb_require_fvg": True, "smc_orb_require_ema_momentum": False}),
        ("mom_only", {"smc_orb_path_mode": "mom_only", "smc_orb_require_fvg": False, "smc_orb_require_ema_momentum": True}),
        ("fvg_preferred", {"smc_orb_path_mode": "fvg_preferred", "smc_orb_require_fvg": False, "smc_orb_require_ema_momentum": False}),
    ]:
        p = deepcopy(work); p.update(flags); ev(f"path_{mode}", "path", p)
    lock("path", "smc_orb_path_mode", "smc_orb_require_fvg", "smc_orb_require_ema_momentum")

    # 3 retest
    print("\n--- 3 Retest ---", flush=True)
    for mode in ["touch", "enter", "mid", "reject"]:
        p = deepcopy(work); p["smc_orb_fvg_retest_mode"] = mode; ev(f"retest_{mode}", "retest", p)
    lock("retest", "smc_orb_fvg_retest_mode")

    # 4 pad
    print("\n--- 4 OR pad ---", flush=True)
    for pad in [0.0, 0.0002, 0.0004, 0.0005, 0.0008, 0.0010, 0.0012, 0.0015, 0.0020]:
        p = deepcopy(work); p["smc_orb_pad_pct"] = float(pad); ev(f"pad_{pad}", "pad", p)
    lock("pad", "smc_orb_pad_pct")

    # 5 buffer
    print("\n--- 5 Buffer ---", flush=True)
    for b in [0.0, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20]:
        p = deepcopy(work); p["entry_buffer_pct"] = float(b); ev(f"buf_{b}", "buffer", p)
    lock("buffer", "entry_buffer_pct")

    # 6 breakout
    print("\n--- 6 Breakout ---", flush=True)
    for label, flags in [
        ("off", {"smc_orb_require_breakout": False, "smc_orb_breakout_pad_pct": 0.0}),
        ("hard", {"smc_orb_require_breakout": True, "smc_orb_breakout_pad_pct": 0.0}),
        ("hard_buf", {"smc_orb_require_breakout": True, "smc_orb_breakout_pad_pct": 0.0012}),
    ]:
        p = deepcopy(work); p.update(flags); ev(f"bo_{label}", "breakout", p)
    lock("breakout", "smc_orb_require_breakout", "smc_orb_breakout_pad_pct")

    # 7 momentum / ema sep
    print("\n--- 7 Momentum ---", flush=True)
    for on in [False, True]:
        p = deepcopy(work); p["smc_orb_require_ema_momentum"] = on; ev(f"ema_mom_{on}", "ema_mom", p)
    for on in [False, True]:
        p = deepcopy(work); p["smc_orb_require_momentum"] = on; p["smc_orb_momentum_mode"] = "two_bar" if on else "off"; ev(f"bar_mom_{on}", "bar_mom", p)
    for sep in [0.0, 0.02, 0.04, 0.05, 0.07, 0.10]:
        p = deepcopy(work); p["smc_orb_ema_sep_pct"] = float(sep); ev(f"sep_{sep}", "ema_sep", p)
    lock("ema_mom", "smc_orb_require_ema_momentum")
    lock("bar_mom", "smc_orb_require_momentum", "smc_orb_momentum_mode")
    lock("ema_sep", "smc_orb_ema_sep_pct")

    # 8 rejection
    print("\n--- 8 Rejection ---", flush=True)
    for body in [0.45, 0.50, 0.55, 0.60, 0.65]:
        p = deepcopy(work); p["smc_orb_reject_body_min"] = float(body); ev(f"body_{body}", "rej_body", p)
    for wick in [0.20, 0.28, 0.35, 0.40]:
        p = deepcopy(work); p["smc_orb_reject_wick_min"] = float(wick); ev(f"wick_{wick}", "rej_wick", p)
    for mode in ["body_only", "wick_only", "body_or_wick", "both"]:
        p = deepcopy(work); p["smc_orb_reject_mode"] = mode; ev(f"mode_{mode}", "rej_mode", p)
    lock("rej_body", "smc_orb_reject_body_min")
    lock("rej_wick", "smc_orb_reject_wick_min")
    lock("rej_mode", "smc_orb_reject_mode")

    # 9 bias/structure
    print("\n--- 9 Bias ---", flush=True)
    for mode in ["block_opposite", "require_aligned", "aligned_5m"]:
        p = deepcopy(work); p["smc_orb_bias_mode"] = mode; ev(f"bias_{mode}", "bias", p)
    for req in [False, True]:
        p = deepcopy(work); p["smc_orb_require_structure"] = req; ev(f"struct_{req}", "structure", p)
    lock("bias", "smc_orb_bias_mode")
    lock("structure", "smc_orb_require_structure")

    # 10 RSI
    print("\n--- 10 RSI ---", flush=True)
    p = deepcopy(work); p["smc_orb_rsi_enabled"] = False; ev("rsi_off", "rsi_gate", p)
    p = deepcopy(work); p["smc_orb_rsi_enabled"] = True; ev("rsi_on", "rsi_gate", p)
    for lo, hi in [(45, 65), (50, 65), (50, 68), (52, 66), (52, 68), (55, 70), (40, 70)]:
        p = deepcopy(work); p.update({"smc_orb_rsi_enabled": True, "smc_orb_rsi_call_min": lo, "smc_orb_rsi_call_max": hi}); ev(f"call_{lo}_{hi}", "call_rsi", p)
    for lo, hi in [(32, 52), (34, 50), (35, 55), (38, 54), (38, 56), (40, 55), (30, 60)]:
        p = deepcopy(work); p.update({"smc_orb_rsi_enabled": True, "smc_orb_rsi_put_min": lo, "smc_orb_rsi_put_max": hi}); ev(f"put_{lo}_{hi}", "put_rsi", p)
    for on in [False, True]:
        p = deepcopy(work); p["smc_orb_rsi_slope"] = on; ev(f"slope_{on}", "rsi_slope", p)
    bg = best("rsi_gate")
    if bg and bg["params"].get("smc_orb_rsi_enabled") is False:
        work["smc_orb_rsi_enabled"] = False
        print("LOCK rsi OFF", flush=True)
    else:
        work["smc_orb_rsi_enabled"] = True
        lock("call_rsi", "smc_orb_rsi_call_min", "smc_orb_rsi_call_max")
        lock("put_rsi", "smc_orb_rsi_put_min", "smc_orb_rsi_put_max")
    lock("rsi_slope", "smc_orb_rsi_slope")

    # 11 volume
    print("\n--- 11 Volume ---", flush=True)
    for v in [0.0, 0.90, 0.95, 1.00, 1.10, 1.20, 1.30, 1.50]:
        p = deepcopy(work); p["volume_min"] = float(v); ev(f"vol_{v}", "volume", p)
    lock("volume", "volume_min")

    # 12-14 risk
    print("\n--- 12-14 Risk ---", flush=True)
    for s in [0.70, 0.80, 0.90, 1.00, 1.20, 1.40, 1.50]:
        p = deepcopy(work); p["stop_atr_mult"] = float(s); ev(f"sl_{s}", "stop", p)
    for t in [1.00, 1.20, 1.40, 1.60, 1.80, 2.00, 2.20, 2.50]:
        p = deepcopy(work); p["target_atr_mult"] = float(t); ev(f"tp_{t}", "target", p)
    lock("stop", "stop_atr_mult")
    lock("target", "target_atr_mult")
    sl_c = sorted([r for r in rows if r["group"] == "stop" and r["metrics"]["trades"] >= 3], key=lambda r: r["score"], reverse=True)[:3]
    tg_c = sorted([r for r in rows if r["group"] == "target" and r["metrics"]["trades"] >= 3], key=lambda r: r["score"], reverse=True)[:3]
    for a, b in product(sl_c, tg_c):
        p = deepcopy(work)
        p["stop_atr_mult"] = a["params"]["stop_atr_mult"]
        p["target_atr_mult"] = b["params"]["target_atr_mult"]
        ev(f"rr_{p['stop_atr_mult']}_{p['target_atr_mult']}", "rr", p)
    lock("rr", "stop_atr_mult", "target_atr_mult")
    for tr in [0.0, 0.50, 0.75, 1.00, 1.25]:
        p = deepcopy(work); p["trailing_atr_mult"] = float(tr); ev(f"trail_{tr}", "trail", p)
    lock("trail", "trailing_atr_mult")

    # 15 hold / window / scan
    print("\n--- 15 Hold/Window/Scan ---", flush=True)
    for h in [6, 8, 10, 12, 14, 16, 20]:
        p = deepcopy(work); p["max_hold_bars"] = int(h); ev(f"hold_{h}", "hold", p)
    lock("hold", "max_hold_bars")
    for start in [9 * 60 + 25, 9 * 60 + 30, 9 * 60 + 35, 9 * 60 + 40]:
        p = deepcopy(work); p["smc_orb_entry_start_min"] = start; ev(f"start_{start}", "start", p)
    for cut in [10 * 60 + 15, 10 * 60 + 30, 10 * 60 + 45, 11 * 60]:
        p = deepcopy(work); p["smc_orb_entry_cutoff_min"] = cut; ev(f"cut_{cut}", "cutoff", p)
    lock("start", "smc_orb_entry_start_min")
    lock("cutoff", "smc_orb_entry_cutoff_min")
    for s in [1, 2, 3, 5]:
        p = deepcopy(work); p["smc_entry_scan_every"] = s; ev(f"scan_{s}", "scan", p)
    for m in [3, 5, 8, 10, 12]:
        p = deepcopy(work); p["smc_min_bars_between"] = m; ev(f"between_{m}", "between", p)
    lock("scan", "smc_entry_scan_every")
    lock("between", "smc_min_bars_between")

    # Stability
    print("\n--- Stability ---", flush=True)
    for dg in [-0.1, -0.05, 0.0, 0.05, 0.1]:
        p = deepcopy(work); p["fvg_min_gap_pct"] = max(0.008, float(work["fvg_min_gap_pct"]) + dg); ev(f"stab_gap_{p['fvg_min_gap_pct']:.3f}", "stability", p)
    for ds in [-0.1, 0.0, 0.1]:
        p = deepcopy(work); p["stop_atr_mult"] = max(0.5, float(work["stop_atr_mult"]) + ds); ev(f"stab_sl_{p['stop_atr_mult']}", "stability", p)
    for dt in [-0.2, 0.0, 0.2]:
        p = deepcopy(work); p["target_atr_mult"] = max(0.8, float(work["target_atr_mult"]) + dt); ev(f"stab_tp_{p['target_atr_mult']}", "stability", p)

    # Combos + WF
    print("\n--- Combos / WF ---", flush=True)
    combos = [deepcopy(base), deepcopy(work)]
    for d_sl, d_tg in product([-0.1, 0.0, 0.1], [-0.2, 0.0, 0.2]):
        p = deepcopy(work)
        p["stop_atr_mult"] = max(0.5, float(p["stop_atr_mult"]) + d_sl)
        p["target_atr_mult"] = max(0.8, float(p["target_atr_mult"]) + d_tg)
        combos.append(p)
    seen, unique = set(), []
    for p in combos:
        key = json.dumps(p, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    combo_train = [ev(f"combo_{i}", "combo", p) for i, p in enumerate(unique)]
    top = sorted(
        [r for r in combo_train if r["metrics"]["trades"] >= MIN_TRADES and r["metrics"]["expectancy"] > 0],
        key=lambda r: r["score"],
        reverse=True,
    )[:8] or sorted(combo_train, key=lambda r: r["score"], reverse=True)[:5]

    val_rows = []
    for tr in top:
        vr = ev(tr["label"] + "_val", "combo_val", tr["params"], dataset="val")
        val_rows.append({**vr, "train_score": tr["score"]})

    recommended = sorted(
        val_rows,
        key=lambda r: (
            1 if r["metrics"]["expectancy"] > 0 else 0,
            1 if r["metrics"]["win_rate"] >= 70 else 0,
            r["score"],
            r.get("train_score", 0),
        ),
        reverse=True,
    )[0] if val_rows else None

    rec_oos = rec_full = None
    if recommended:
        rec_oos = ev("recommended_oos", "oos", recommended["params"], dataset="oos")
        rec_full = ev("recommended_full", "full", recommended["params"], dataset="full")

    eligible = [r for r in rows if r["dataset"] == "train" and r["metrics"]["trades"] >= MIN_TRADES]
    ranked = sorted(eligible, key=lambda r: r["score"], reverse=True)
    picks = {g: best(g) for g in [
        "fvg_gap", "path", "retest", "pad", "buffer", "breakout", "ema_mom", "bar_mom", "ema_sep",
        "rej_body", "rej_wick", "rej_mode", "bias", "structure", "call_rsi", "put_rsi", "rsi_slope",
        "volume", "stop", "target", "rr", "trail", "hold", "start", "cutoff", "scan", "between",
    ]}

    report = {
        "strategy": STRATEGY_CODE,
        "data_source": source,
        "date_range": {"from": fr, "to": to},
        "bars": len(df),
        "elapsed_sec": round(time.time() - t0, 1),
        "fvg_gap_units": "gap/mid*100 >= fvg_min_gap_pct",
        "walk_forward": {"train": len(train), "val": len(val), "oos": len(oos)},
        "baseline": {"params": base, "full": base_full, "train": base_train, "val": base_val, "oos": base_oos},
        "ofat_best": {k: ({"label": v["label"], "score": v["score"], "metrics": v["metrics"], "params": {kk: v["params"].get(kk) for kk in v["params"]}} if v else None) for k, v in picks.items()},
        "working_params": work,
        "top10_train": [
            {"rank": i, "label": r["label"], "group": r["group"], "score": r["score"], "metrics": r["metrics"], "params": r["params"]}
            for i, r in enumerate(ranked[:10], 1)
        ],
        "recommended": recommended,
        "recommended_oos": rec_oos,
        "recommended_full": rec_full,
        "notes": [
            "Baseline already ~100% WR with small expectancy; score prioritizes expectancy/PnL while preserving high WR.",
            "ORB minutes fixed at 15 via prepare_mtf_frames session_orbs.",
            "FVG gap uses detect_fvg units (gap/mid*100), not raw fraction.",
        ],
    }
    out = os.environ.get("REPORT_PATH", "/tmp/optimize_scalp_smc003_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote {out} elapsed={report['elapsed_sec']}s", flush=True)
    print("\n=== TOP 10 TRAIN ===", flush=True)
    for r in report["top10_train"]:
        m = r["metrics"]
        print(f"{r['rank']:2}. [{r['group']}] {r['label']} sc={r['score']} WR={m['win_rate']}% PF={m['profit_factor']} EXP={m['expectancy']} tr={m['trades']} PnL={m['total_pnl']}", flush=True)
    if recommended:
        print("\n=== RECOMMENDED ===", flush=True)
        print(json.dumps({
            "params": recommended["params"],
            "val": recommended["metrics"],
            "oos": (rec_oos or {}).get("metrics"),
            "full": (rec_full or {}).get("metrics"),
        }, indent=2, default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
