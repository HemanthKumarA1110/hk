#!/usr/bin/env python3
"""Refine SCALP-BT-004 from OFAT findings — avoid stacking all winners.

Data: /tmp/bt004_candles.pkl (Nifty 60d Angel 1m).
"""

from __future__ import annotations

import json
import os
import pickle
import sys
from copy import deepcopy
from itertools import product
from typing import Any

STRATEGY_CODE = "SCALP-BT-004"
INSTRUMENT_KEY = "nifty50"
MIN_TRADES = int(os.environ.get("MIN_TRADES", "6"))
CANDLE_CACHE = os.environ.get("CANDLE_CACHE", "/tmp/bt004_candles.pkl")


def get_candles():
    with open(CANDLE_CACHE, "rb") as f:
        p = pickle.load(f)
    return p["df"], p["source"], p["from_date"], p["to_date"]


def spot_ref(df) -> float:
    return float(df["close"].astype(float).median())


def pts_to_pct(pts, spot):
    return float(pts) / max(spot, 1.0)


def baseline():
    from trading_shared.strategies.scalping_desk.orb_breakout_tuning import ORB_BREAKOUT_NIFTY_DEFAULTS

    return dict(ORB_BREAKOUT_NIFTY_DEFAULTS)


def run_bt(df, lot, capital, orb):
    from trading_shared.strategies.scalping_desk.backtest import run_strategy_backtest

    return run_strategy_backtest(
        df, "1m", lot, capital,
        strategy_code=STRATEGY_CODE,
        instrument_key=INSTRUMENT_KEY,
        params={"orb_breakout": orb},
        max_loss_per_day=5000,
        max_trades_per_day=5,
    )


def _hhmm(ts: str) -> int | None:
    try:
        part = ts.split("T")[1][:5] if "T" in ts else ts.split(" ")[1][:5]
        h, m = part.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


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
        "pf": round(gp / gl, 2) if gl else round(gp, 2),
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
    morning, afternoon = [], []
    buckets = {k: [] for k in (
        "09:20-09:30", "09:30-09:45", "09:45-10:00", "10:00-10:15", "10:15-10:30",
        "13:30-14:00", "14:00-14:30", "14:30-14:45",
    )}
    for t in trades:
        m = _hhmm(str(t.get("entry_time") or ""))
        if m is None:
            continue
        if 9 * 60 + 20 <= m <= 10 * 60 + 30:
            morning.append(t)
        elif 13 * 60 + 30 <= m <= 14 * 60 + 45:
            afternoon.append(t)
        if 9 * 60 + 20 <= m < 9 * 60 + 30:
            buckets["09:20-09:30"].append(t)
        elif 9 * 60 + 30 <= m < 9 * 60 + 45:
            buckets["09:30-09:45"].append(t)
        elif 9 * 60 + 45 <= m < 10 * 60:
            buckets["09:45-10:00"].append(t)
        elif 10 * 60 <= m < 10 * 60 + 15:
            buckets["10:00-10:15"].append(t)
        elif 10 * 60 + 15 <= m <= 10 * 60 + 30:
            buckets["10:15-10:30"].append(t)
        elif 13 * 60 + 30 <= m < 14 * 60:
            buckets["13:30-14:00"].append(t)
        elif 14 * 60 <= m < 14 * 60 + 30:
            buckets["14:00-14:30"].append(t)
        elif 14 * 60 + 30 <= m <= 14 * 60 + 45:
            buckets["14:30-14:45"].append(t)
    mw, ml = streaks(trades)
    wins = [t for t in trades if float(t.get("pnl") or 0) > 0]
    losses = [t for t in trades if float(t.get("pnl") or 0) <= 0]

    regimes = {}
    if candles is not None and trades:
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

    def wr(rows):
        if not rows:
            return None
        return round(sum(1 for t in rows if float(t.get("pnl") or 0) > 0) / len(rows) * 100, 2)

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
        "put_n": len(puts),
        "call_wr": wr(calls),
        "put_wr": wr(puts),
        "morning_n": len(morning),
        "afternoon_n": len(afternoon),
        "morning_wr": wr(morning),
        "afternoon_wr": wr(afternoon),
        "session_detail": {
            "morning": subset(morning),
            "afternoon": subset(afternoon),
            "CALL": subset(calls),
            "PUT": subset(puts),
        },
        "time_buckets": {k: subset(v) for k, v in buckets.items()},
        "regimes": {k: subset(v) for k, v in regimes.items()},
    }


def score(m, ref_n=15):
    n = m["trades"]
    if n < MIN_TRADES:
        return -100.0 + n
    wr = float(m["win_rate"])
    pf = min(float(m["profit_factor"]), 4.0)
    exp = float(m["expectancy"])
    dd = float(m["max_drawdown"])
    pnl = float(m["total_pnl"])
    if exp <= 0:
        return wr * 0.5 + pf * 2 - 25
    tr = n / max(ref_n, 1)
    trade_sc = max(0, min(tr, 2)) * 14
    if tr < 0.5:
        trade_sc -= 15
    return wr * 2.2 + pf * 16 + max(min(exp / 150, 18), -18) + trade_sc + max(min(pnl / 4000, 14), -14) - min(dd / 800, 35)


def split_wf(df):
    n = len(df)
    return (
        df.iloc[: int(n * 0.6)].reset_index(drop=True),
        df.iloc[int(n * 0.6) : int(n * 0.8)].reset_index(drop=True),
        df.iloc[int(n * 0.8) :].reset_index(drop=True),
    )


def main():
    import trading_shared.strategies.scalping_desk.backtest as bt
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

    bt.MAX_BACKTEST_BARS = 40000
    df, source, fr, to = get_candles()
    spot = spot_ref(df)
    lot = int(INSTRUMENTS[INSTRUMENT_KEY]["lot_size"])
    capital = 100000.0
    train, val, oos = split_wf(df)
    base = baseline()

    print(f"=== REFINE {STRATEGY_CODE} bars={len(df)} spot={spot:.1f} ===", flush=True)

    base_m = metrics(run_bt(df, lot, capital, base), df)
    print("BASELINE", json.dumps({k: base_m[k] for k in (
        "trades", "win_rate", "profit_factor", "expectancy", "total_pnl", "max_drawdown",
        "winning_trades", "losing_trades", "avg_win", "avg_loss",
        "max_consec_wins", "max_consec_losses",
        "call_n", "call_wr", "put_n", "put_wr", "morning_n", "morning_wr", "afternoon_n", "afternoon_wr",
    )}), flush=True)

    # Core scaffold from OFAT: afternoon ON, prior OFF (unlocks trades), OR medium
    scaffold = deepcopy(base)
    scaffold.update({
        "orb_entry_cutoff_min": 14 * 60 + 45,
        "orb_prior_mode": "off",
        "orb_require_inside_or": False,
        "orb_or_range_min": 40.0,
        "orb_or_range_max": 80.0,
        "orb_skip_wide_or": True,
        "orb_vol_min": 1.15,
        "orb_require_two_bar_momentum": False,  # OFAT: mom OFF was strong
        "orb_momentum_mode": "two_bar",
        "orb_rsi_call_min": 52,
        "orb_rsi_call_max": 66,
        "orb_rsi_put_min": 32,
        "orb_rsi_put_max": 46,
        "orb_ema_fast": 8,
        "orb_ema_slow": 20,
        "orb_buffer_pct": pts_to_pct(2, spot),
        "orb_stop_pts": 6.0,
        "orb_target_pts": 12.0,
        "orb_max_hold_bars": 10,
        "orb_min_separation_pct": 0.0,
        "orb_min_body_pct": 0.0,
        "orb_require_vwap": False,
        "orb_require_rsi_slope": False,
        "orb_vol_lookback": 0,
    })

    rows = []

    def ev(label, group, orb, frame=None, dataset="train"):
        data = frame if frame is not None else train
        m = metrics(run_bt(data, lot, capital, orb), data)
        sc = score(m, ref_n=12)
        row = {"label": label, "group": group, "dataset": dataset, "params": dict(orb), "metrics": m, "score": round(sc, 2)}
        rows.append(row)
        print(
            f"{group:10} {label:36} n={m['trades']:>3} WR={m['win_rate']:>6}% "
            f"PF={m['profit_factor']:>5} EXP={m['expectancy']:>8} PnL={m['total_pnl']:>9} "
            f"DD={m['max_drawdown']:>8} sc={sc:>6.1f}",
            flush=True,
        )
        return row

    print("\n--- Scaffold ---", flush=True)
    ev("scaffold", "core", scaffold)

    # Sequential light OFAT on scaffold (one factor)
    print("\n--- OR on scaffold ---", flush=True)
    for rmin, rmax in [(35, 80), (40, 80), (40, 90), (45, 80), (45, 90), (30, 80), (40, 100)]:
        o = deepcopy(scaffold)
        o.update({"orb_or_range_min": float(rmin), "orb_or_range_max": float(rmax)})
        ev(f"or_{rmin}_{rmax}", "or", o)

    print("\n--- Buffer on scaffold ---", flush=True)
    for pts in [0, 1, 2, 3, 4, 5]:
        o = deepcopy(scaffold)
        o["orb_buffer_pct"] = pts_to_pct(pts, spot)
        ev(f"buf_{pts}", "buf", o)

    print("\n--- Prior on scaffold ---", flush=True)
    for name, mode in [("off", "off"), ("close", "close_inside"), ("inside", "inside"), ("not_beyond", "not_beyond")]:
        o = deepcopy(scaffold)
        o["orb_prior_mode"] = mode
        o["orb_require_inside_or"] = mode in ("close_inside", "inside")
        ev(f"prior_{name}", "prior", o)

    print("\n--- Volume on scaffold ---", flush=True)
    for v in [1.0, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35]:
        o = deepcopy(scaffold)
        o["orb_vol_min"] = float(v)
        ev(f"vol_{v}", "vol", o)

    print("\n--- Momentum on scaffold ---", flush=True)
    for flag, mode, atr in [
        (False, "two_bar", 0.0),
        (True, "two_bar", 0.0),
        (True, "directional", 0.0),
        (True, "atr", 0.15),
        (True, "atr", 0.25),
    ]:
        o = deepcopy(scaffold)
        o.update({"orb_require_two_bar_momentum": flag, "orb_momentum_mode": mode, "orb_momentum_atr_mult": atr})
        ev(f"mom_{mode}_{flag}_{atr}", "mom", o)

    print("\n--- SL/TP on scaffold ---", flush=True)
    for sl, tp in product([5, 5.5, 6, 6.5, 7], [10, 12, 14, 15, 18]):
        if tp <= sl:
            continue
        o = deepcopy(scaffold)
        o.update({"orb_stop_pts": float(sl), "orb_target_pts": float(tp)})
        ev(f"rr_{sl}_{tp}", "rr", o)

    print("\n--- Hold on scaffold ---", flush=True)
    for h in [5, 6, 7, 8, 10, 12]:
        o = deepcopy(scaffold)
        o["orb_max_hold_bars"] = int(h)
        ev(f"hold_{h}", "hold", o)

    print("\n--- Body / sep light ---", flush=True)
    for b in [0.0, 0.3, 0.4]:
        o = deepcopy(scaffold)
        o["orb_min_body_pct"] = float(b)
        ev(f"body_{b}", "body", o)
    for sep in [0.0, 0.02]:
        o = deepcopy(scaffold)
        o["orb_min_separation_pct"] = float(sep)
        ev(f"sep_{sep}", "sep", o)

    # Pick best per group with n>=MIN and exp>0 preferred
    def best(group):
        g = [r for r in rows if r["group"] == group and r["dataset"] == "train" and r["metrics"]["trades"] >= MIN_TRADES]
        pos = [r for r in g if r["metrics"]["expectancy"] > 0]
        pool = pos or g
        if not pool:
            return None
        return max(pool, key=lambda r: (r["score"], r["metrics"]["win_rate"], r["metrics"]["trades"]))

    picks = {g: best(g) for g in ("or", "buf", "prior", "vol", "mom", "rr", "hold", "body", "sep")}
    print("\n--- Picks ---", flush=True)
    work = deepcopy(scaffold)
    apply_map = {
        "or": ("orb_or_range_min", "orb_or_range_max"),
        "buf": ("orb_buffer_pct",),
        "prior": ("orb_prior_mode", "orb_require_inside_or"),
        "vol": ("orb_vol_min",),
        "mom": ("orb_require_two_bar_momentum", "orb_momentum_mode", "orb_momentum_atr_mult"),
        "rr": ("orb_stop_pts", "orb_target_pts"),
        "hold": ("orb_max_hold_bars",),
        "body": ("orb_min_body_pct",),
        "sep": ("orb_min_separation_pct",),
    }
    for g, row in picks.items():
        if not row:
            print(f"  {g}: none", flush=True)
            continue
        print(f"  {g}: {row['label']} sc={row['score']} WR={row['metrics']['win_rate']} n={row['metrics']['trades']}", flush=True)
        for k in apply_map[g]:
            if k in row["params"]:
                work[k] = row["params"][k]

    # Curated combos — never stack body+sep+tight vol+tight OR all at once
    print("\n--- Curated combos ---", flush=True)
    combos = []

    # A: scaffold alone
    combos.append(("A_scaffold", deepcopy(scaffold)))

    # B: OFAT-locked work
    combos.append(("B_locked", deepcopy(work)))

    # C: OR40-80 + mom off + vol1.15 + buf2 + rr6/12 (concept-aligned)
    c = deepcopy(scaffold)
    combos.append(("C_concept", c))

    # D: OR40-80 + mom off + vol1.20 + CALL/PUT RSI + buf3 + hold8
    c = deepcopy(scaffold)
    c.update({
        "orb_vol_min": 1.20,
        "orb_buffer_pct": pts_to_pct(3, spot),
        "orb_max_hold_bars": 8,
        "orb_stop_pts": 6.0,
        "orb_target_pts": 12.0,
    })
    combos.append(("D_vol120_buf3_h8", c))

    # E: OR45-80 + mom off + vol1.15 + target 14
    c = deepcopy(scaffold)
    c.update({"orb_or_range_min": 45.0, "orb_or_range_max": 80.0, "orb_target_pts": 14.0})
    combos.append(("E_or45_tp14", c))

    # F: OR40-80 + atr mom 0.25 + vol1.15
    c = deepcopy(scaffold)
    c.update({"orb_require_two_bar_momentum": True, "orb_momentum_mode": "atr", "orb_momentum_atr_mult": 0.25})
    combos.append(("F_atr025", c))

    # G: OR40-90 + mom off + vol1.10 + stop5.5 target12
    c = deepcopy(scaffold)
    c.update({
        "orb_or_range_max": 90.0,
        "orb_vol_min": 1.10,
        "orb_stop_pts": 5.5,
        "orb_target_pts": 12.0,
    })
    combos.append(("G_wide_sl55", c))

    # H: morning-only scaffold
    c = deepcopy(scaffold)
    c["orb_entry_cutoff_min"] = 10 * 60 + 30
    combos.append(("H_morning", c))

    # I: prior close_inside restored + looser vol 1.05 + mom off
    c = deepcopy(scaffold)
    c.update({
        "orb_prior_mode": "close_inside",
        "orb_require_inside_or": True,
        "orb_vol_min": 1.05,
    })
    combos.append(("I_prior_close_vol105", c))

    # J: body 0.3 only on scaffold
    c = deepcopy(scaffold)
    c["orb_min_body_pct"] = 0.3
    combos.append(("J_body30", c))

    # K: EMA 9/21 restore
    c = deepcopy(scaffold)
    c.update({"orb_ema_fast": 9, "orb_ema_slow": 21})
    combos.append(("K_ema921", c))

    # L: best rr from OFAT if available
    if picks.get("rr"):
        c = deepcopy(scaffold)
        c["orb_stop_pts"] = picks["rr"]["params"]["orb_stop_pts"]
        c["orb_target_pts"] = picks["rr"]["params"]["orb_target_pts"]
        if picks.get("or"):
            c["orb_or_range_min"] = picks["or"]["params"]["orb_or_range_min"]
            c["orb_or_range_max"] = picks["or"]["params"]["orb_or_range_max"]
        if picks.get("vol"):
            c["orb_vol_min"] = picks["vol"]["params"]["orb_vol_min"]
        combos.append(("L_or_vol_rr", c))

    # M: WR focus — higher vol + OR45-80 + mom off
    c = deepcopy(scaffold)
    c.update({"orb_or_range_min": 45.0, "orb_or_range_max": 80.0, "orb_vol_min": 1.25})
    combos.append(("M_wr_focus", c))

    # N: stability — OR40-80 vol1.15 mom off buf2 hold10 SL6 TP12 EMA8/20 RSI52-66/32-46
    combos.append(("N_stable_core", deepcopy(scaffold)))

    for name, orb in combos:
        ev(name, "combo", orb)

    # Rank combos with positive expectancy
    eligible = [
        r for r in rows
        if r["group"] == "combo" and r["metrics"]["trades"] >= MIN_TRADES and r["metrics"]["expectancy"] > 0
    ]
    if not eligible:
        eligible = [r for r in rows if r["group"] == "combo" and r["metrics"]["trades"] >= MIN_TRADES]
    ranked = sorted(eligible, key=lambda r: (r["score"], r["metrics"]["win_rate"], r["metrics"]["trades"]), reverse=True)

    # Also include strong non-combo OFAT rows in top10
    extras = [
        r for r in rows
        if r["group"] != "combo" and r["metrics"]["trades"] >= MIN_TRADES and r["metrics"]["expectancy"] > 0
    ]
    merged = sorted(ranked + extras, key=lambda r: (r["score"], r["metrics"]["win_rate"]), reverse=True)
    # dedupe by label
    seen = set()
    top_pool = []
    for r in merged:
        if r["label"] in seen:
            continue
        seen.add(r["label"])
        top_pool.append(r)

    rec = ranked[0] if ranked else (top_pool[0] if top_pool else None)
    if not rec:
        print("No viable recommendation", flush=True)
        return 1
    rec_params = deepcopy(rec["params"])

    # Stability neighbours of recommendation
    print("\n--- Stability ---", flush=True)
    for pts in [1, 2, 3, 4]:
        o = deepcopy(rec_params)
        o["orb_buffer_pct"] = pts_to_pct(pts, spot)
        ev(f"stab_buf_{pts}", "stab", o)
    for v in [1.10, 1.15, 1.20, 1.25]:
        o = deepcopy(rec_params)
        o["orb_vol_min"] = float(v)
        ev(f"stab_vol_{v}", "stab", o)
    for sl, tp in [(5.5, 11), (6, 12), (6.5, 13), (7, 14)]:
        o = deepcopy(rec_params)
        o.update({"orb_stop_pts": float(sl), "orb_target_pts": float(tp)})
        ev(f"stab_rr_{sl}_{tp}", "stab", o)

    print("\n--- Walk-forward ---", flush=True)
    for label, frame, ds in [
        ("rec_train", train, "train"),
        ("rec_val", val, "val"),
        ("rec_oos", oos, "oos"),
        ("rec_full", df, "full"),
        ("base_full", df, "full"),
    ]:
        params = base if label == "base_full" else rec_params
        ev(label, "final", params, frame=frame, dataset=ds)

    rec_train = next(r for r in rows if r["label"] == "rec_train")
    rec_val = next(r for r in rows if r["label"] == "rec_val")
    rec_oos = next(r for r in rows if r["label"] == "rec_oos")
    rec_full = next(r for r in rows if r["label"] == "rec_full")

    # Prefer stab neighbour if clearly better on train and still positive
    stab = [r for r in rows if r["group"] == "stab" and r["metrics"]["expectancy"] > 0 and r["metrics"]["trades"] >= MIN_TRADES]
    if stab:
        best_stab = max(stab, key=lambda r: (r["score"], r["metrics"]["win_rate"]))
        if best_stab["score"] > rec["score"] + 3 and best_stab["metrics"]["win_rate"] >= rec_full["metrics"]["win_rate"] - 2:
            # re-validate that neighbour
            print(f"NOTE promoting stability neighbour {best_stab['label']}", flush=True)
            rec_params = deepcopy(best_stab["params"])
            for label, frame, ds in [
                ("rec_train", train, "train"),
                ("rec_val", val, "val"),
                ("rec_oos", oos, "oos"),
                ("rec_full", df, "full"),
            ]:
                # overwrite final rows by appending new labels
                ev(label + "_stab", "final", rec_params, frame=frame, dataset=ds)
            rec_train = next(r for r in rows if r["label"] == "rec_train_stab")
            rec_val = next(r for r in rows if r["label"] == "rec_val_stab")
            rec_oos = next(r for r in rows if r["label"] == "rec_oos_stab")
            rec_full = next(r for r in rows if r["label"] == "rec_full_stab")
            rec = best_stab

    # Loss autopsy
    full_res = run_bt(df, lot, capital, rec_params)
    losses = [t for t in (full_res.get("trades") or []) if float(t.get("pnl") or 0) <= 0]
    autopsy = {"n": len(losses), "by_exit": {}, "by_side": subset(losses)}
    for t in losses:
        reason = str(t.get("exit_reason") or "?")
        autopsy["by_exit"][reason] = autopsy["by_exit"].get(reason, 0) + 1

    report = {
        "strategy": STRATEGY_CODE,
        "source": source,
        "date_range": {"from": fr, "to": to},
        "bars": len(df),
        "spot_ref": spot,
        "baseline_full": {"params": base, "metrics": base_m},
        "scaffold": scaffold,
        "ofat_picks": {k: (v["label"] if v else None) for k, v in picks.items()},
        "recommended": {
            "label": rec["label"],
            "params": rec_params,
            "train": rec_train["metrics"],
            "val": rec_val["metrics"],
            "oos": rec_oos["metrics"],
            "full": rec_full["metrics"],
        },
        "top10": [
            {
                "rank": i,
                "label": r["label"],
                "group": r["group"],
                "score": r["score"],
                "win_rate": r["metrics"]["win_rate"],
                "profit_factor": r["metrics"]["profit_factor"],
                "expectancy": r["metrics"]["expectancy"],
                "total_pnl": r["metrics"]["total_pnl"],
                "max_drawdown": r["metrics"]["max_drawdown"],
                "trades": r["metrics"]["trades"],
            }
            for i, r in enumerate(top_pool[:10], 1)
        ],
        "loss_autopsy": autopsy,
        "notes": [
            "True baseline remains extremely sparse (stacked prior+vol+morning cutoff).",
            "Scaffold enables afternoon + prior OFF + mom OFF + OR 40-80 from OFAT.",
            "Combos avoid stacking every OFAT winner (that collapse was observed).",
            "Walk-forward 60/20/20; OOS not used for parameter search.",
        ],
    }
    out = os.environ.get("REPORT_PATH", "/tmp/optimize_scalp_bt004_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote {out}", flush=True)
    print("\n=== TOP 10 ===", flush=True)
    for r in report["top10"]:
        print(
            f"{r['rank']:2}. [{r['group']}] {r['label']} WR={r['win_rate']}% PF={r['profit_factor']} "
            f"EXP={r['expectancy']} n={r['trades']} PnL={r['total_pnl']} DD={r['max_drawdown']}",
            flush=True,
        )
    print("\n=== RECOMMENDED ===", flush=True)
    print(json.dumps(rec_params, indent=2, default=str), flush=True)
    slim = lambda m: {k: m.get(k) for k in (
        "trades", "win_rate", "profit_factor", "expectancy", "total_pnl", "max_drawdown",
        "avg_win", "avg_loss", "max_consec_wins", "max_consec_losses",
        "call_n", "call_wr", "put_n", "put_wr", "morning_n", "morning_wr", "afternoon_n", "afternoon_wr",
        "session_detail", "regimes", "time_buckets",
    )}
    print("\n=== WF ===", flush=True)
    print(json.dumps({
        "train": slim(rec_train["metrics"]),
        "val": slim(rec_val["metrics"]),
        "oos": slim(rec_oos["metrics"]),
        "full": slim(rec_full["metrics"]),
        "baseline": slim(base_m),
    }, indent=2, default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
