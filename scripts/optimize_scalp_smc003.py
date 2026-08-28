#!/usr/bin/env python3
"""SCALP-SMC-003 (SMC ORB + FVG) OFAT + walk-forward — Nifty 50.

Uses existing run_single_smc_backtest. Does not modify Bank SMC-006.

    PYTHONUNBUFFERED=1 python /app/scripts/optimize_scalp_smc003.py

Note on FVG gap units (existing detect_fvg):
    gap / mid * 100 >= fvg_min_gap_pct
So 0.80 means 0.80% of mid; current default 0.008 is nearly unfiltered.
"""

from __future__ import annotations

import json
import os
import pickle
import sys
from copy import deepcopy
from itertools import product
from typing import Any

STRATEGY_ID = "smc_orb_fvg"
STRATEGY_CODE = "SCALP-SMC-003"
INSTRUMENT_KEY = "nifty50"
MIN_TRADES = int(os.environ.get("MIN_TRADES", "5"))
CANDLE_CACHE = os.environ.get("CANDLE_CACHE", "/tmp/bt004_candles.pkl")
QUICK = os.environ.get("QUICK", "0") == "1"
_REGIME_ALLOW: set[str] | None = None


def baseline_params() -> dict[str, Any]:
    from trading_shared.strategies.scalping_desk.smc_orb_fvg_tuning import SMC_ORB_FVG_NIFTY_LEGACY

    return dict(SMC_ORB_FVG_NIFTY_LEGACY)


def get_candles():
    with open(CANDLE_CACHE, "rb") as f:
        p = pickle.load(f)
    print(f"Loaded cache {CANDLE_CACHE}: bars={len(p['df']):,}", flush=True)
    return p["df"], p["source"], p["from_date"], p["to_date"]


def set_regime_filter(regimes: set[str] | None = None) -> None:
    global _REGIME_ALLOW
    _REGIME_ALLOW = regimes


def run_bt(candles, lot, capital, params):
    from trading_shared.strategies.scalping_desk.smc_backtest import run_single_smc_backtest
    from trading_shared.strategies.scalping_desk.smc_scalping_engine import evaluate_orb_fvg_setup
    import trading_shared.strategies.scalping_desk.smc_scalping_engine as eng

    if _REGIME_ALLOW is not None:
        orig = eng.evaluate_orb_fvg_setup

        def gated(mtf, p):
            setup = orig(mtf, p)
            if setup is None:
                return None
            try:
                from trading_shared.strategies.scalping_desk.market_context import detect_regime_from_candles

                reg = str(detect_regime_from_candles(mtf.df_1m.tail(60)).value).upper()
                if reg not in {x.upper() for x in _REGIME_ALLOW}:
                    return None
            except Exception:
                pass
            return setup

        eng.evaluate_orb_fvg_setup = gated
        eng.SMC_EVALUATORS["smc_orb_fvg"] = gated
        try:
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
        finally:
            eng.evaluate_orb_fvg_setup = evaluate_orb_fvg_setup
            eng.SMC_EVALUATORS["smc_orb_fvg"] = evaluate_orb_fvg_setup

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
        return {"n": 0, "wr": None, "pnl": 0.0, "pf": None, "exp": None, "dd": 0.0, "wins": 0, "losses": 0}
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


def _hhmm(ts: str) -> int | None:
    try:
        part = ts.split("T")[1][:5] if "T" in ts else ts.split(" ")[1][:5]
        h, m = part.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return None


def metrics(res, candles=None):
    trades = res.get("trades") or []
    n = int(res.get("total_trades") or 0)
    pnl = float(res.get("total_pnl") or 0)
    calls = [t for t in trades if str(t.get("signal_type")).upper() == "CALL"]
    puts = [t for t in trades if str(t.get("signal_type")).upper() == "PUT"]
    morning, afternoon = [], []
    buckets = {k: [] for k in (
        "09:25-09:30", "09:30-09:45", "09:45-10:00", "10:00-10:15", "10:15-10:30", "10:30-10:45", "10:45-11:00",
    )}
    fvg_entries, mom_entries = [], []
    for t in trades:
        conds = " ".join(str(c) for c in (t.get("conditions") or t.get("indicators", {}).get("conditions") or []))
        if "fvg" in conds.lower():
            fvg_entries.append(t)
        elif "momentum" in conds.lower():
            mom_entries.append(t)
        m = _hhmm(str(t.get("entry_time") or ""))
        if m is None:
            continue
        if 9 * 60 + 20 <= m <= 10 * 60 + 45:
            morning.append(t)
        elif 13 * 60 + 30 <= m <= 14 * 60 + 45:
            afternoon.append(t)
        if 9 * 60 + 25 <= m < 9 * 60 + 30:
            buckets["09:25-09:30"].append(t)
        elif 9 * 60 + 30 <= m < 9 * 60 + 45:
            buckets["09:30-09:45"].append(t)
        elif 9 * 60 + 45 <= m < 10 * 60:
            buckets["09:45-10:00"].append(t)
        elif 10 * 60 <= m < 10 * 60 + 15:
            buckets["10:00-10:15"].append(t)
        elif 10 * 60 + 15 <= m < 10 * 60 + 30:
            buckets["10:15-10:30"].append(t)
        elif 10 * 60 + 30 <= m < 10 * 60 + 45:
            buckets["10:30-10:45"].append(t)
        elif 10 * 60 + 45 <= m <= 11 * 60:
            buckets["10:45-11:00"].append(t)

    mw, ml = streaks(trades)
    wins = [t for t in trades if float(t.get("pnl") or 0) > 0]
    losses = [t for t in trades if float(t.get("pnl") or 0) <= 0]
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
        "morning_n": len(morning),
        "morning_wr": subset(morning)["wr"],
        "afternoon_n": len(afternoon),
        "afternoon_wr": subset(afternoon)["wr"],
        "session_detail": {
            "morning": subset(morning),
            "afternoon": subset(afternoon),
            "CALL": subset(calls),
            "PUT": subset(puts),
            "FVG": subset(fvg_entries),
            "MOMENTUM": subset(mom_entries),
        },
        "time_buckets": {k: subset(v) for k, v in buckets.items()},
        "regimes": {k: subset(v) for k, v in regimes.items()},
    }


def score(m, ref_n=20):
    n = m["trades"]
    if n < MIN_TRADES:
        return -100.0 + n + float(m["win_rate"]) * 0.05
    wr = float(m["win_rate"])
    pf = min(float(m["profit_factor"]), 4.0)
    exp = float(m["expectancy"])
    dd = float(m["max_drawdown"])
    pnl = float(m["total_pnl"])
    if exp <= 0:
        return wr * 0.6 + pf * 2 - 30
    tr = n / max(ref_n, 1)
    trade_sc = max(0, min(tr, 2.5)) * 12
    if tr < 0.4:
        trade_sc -= 18
    return wr * 2.4 + pf * 14 + max(min(exp / 120, 16), -16) + trade_sc + max(min(pnl / 3500, 12), -12) - min(dd / 700, 30)


def split_wf(df):
    n = len(df)
    return (
        df.iloc[: int(n * 0.6)].reset_index(drop=True),
        df.iloc[int(n * 0.6) : int(n * 0.8)].reset_index(drop=True),
        df.iloc[int(n * 0.8) :].reset_index(drop=True),
    )


def main() -> int:
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

    capital = 100000.0
    lot = int(INSTRUMENTS[INSTRUMENT_KEY]["lot_size"])
    df, source, fr, to = get_candles()
    train, val, oos = split_wf(df)
    base = baseline_params()
    print(f"=== {STRATEGY_CODE} bars={len(df)} {fr}→{to} QUICK={QUICK} WF={len(train)}/{len(val)}/{len(oos)} ===", flush=True)

    print("\n--- BASELINE full ---", flush=True)
    base_full = metrics(run_bt(df, lot, capital, base), df)
    base_train = metrics(run_bt(train, lot, capital, base), train)
    base_val = metrics(run_bt(val, lot, capital, base), val)
    base_oos = metrics(run_bt(oos, lot, capital, base), oos)
    print(json.dumps({
        "full": {k: base_full[k] for k in (
            "trades", "win_rate", "profit_factor", "expectancy", "total_pnl", "max_drawdown",
            "winning_trades", "losing_trades", "avg_win", "avg_loss",
            "max_consec_wins", "max_consec_losses",
            "call_n", "call_wr", "put_n", "put_wr", "morning_n", "morning_wr",
        )},
        "train": {k: base_train[k] for k in ("trades", "win_rate", "profit_factor", "expectancy", "total_pnl", "max_drawdown")},
        "val": {k: base_val[k] for k in ("trades", "win_rate", "profit_factor", "expectancy", "total_pnl", "max_drawdown")},
        "oos": {k: base_oos[k] for k in ("trades", "win_rate", "profit_factor", "expectancy", "total_pnl", "max_drawdown")},
        "regimes": base_full.get("regimes"),
        "session_detail": base_full.get("session_detail"),
        "time_buckets": base_full.get("time_buckets"),
    }, indent=2), flush=True)

    rows: list[dict[str, Any]] = []
    work = deepcopy(base)
    ref_n = max(base_train["trades"], 12)

    def ev(label, group, params, frame=None, dataset="train"):
        data = frame if frame is not None else {"train": train, "val": val, "oos": oos, "full": df}[dataset]
        m = metrics(run_bt(data, lot, capital, params), data)
        sc = score(m, ref_n=ref_n)
        row = {"label": label, "group": group, "dataset": dataset, "params": dict(params), "metrics": m, "score": round(sc, 2)}
        rows.append(row)
        print(
            f"{group:12} {label:34} [{dataset}] n={m['trades']:>3} WR={m['win_rate']:>6}% "
            f"PF={m['profit_factor']:>5} EXP={m['expectancy']:>8} PnL={m['total_pnl']:>9} "
            f"DD={m['max_drawdown']:>8} sc={sc:>6.1f}",
            flush=True,
        )
        return row

    def best(group):
        g = [r for r in rows if r["group"] == group and r["dataset"] == "train" and r["metrics"]["trades"] >= MIN_TRADES]
        pos = [r for r in g if r["metrics"]["expectancy"] > 0]
        pool = pos or g
        if not pool:
            pool = [r for r in rows if r["group"] == group and r["dataset"] == "train" and r["metrics"]["trades"] >= 3]
        if not pool:
            return None
        return max(pool, key=lambda r: (r["score"], r["metrics"]["win_rate"], r["metrics"]["trades"]))

    def lock(group, *keys):
        b = best(group)
        if not b:
            return
        for k in keys:
            if k in b["params"]:
                work[k] = b["params"][k]
        print(f"LOCK {group}: " + ", ".join(f"{k}={work.get(k)}" for k in keys), flush=True)

    # 1 FVG min gap (code units: gap/mid*100)
    print("\n--- 1 FVG gap ---", flush=True)
    gaps = [0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00, 1.20, 1.50, 0.008, 0.05]
    if QUICK:
        gaps = [0.008, 0.10, 0.30, 0.50, 0.80, 1.00, 1.50]
    for g in gaps:
        p = deepcopy(work)
        p["fvg_min_gap_pct"] = float(g)
        ev(f"gap_{g}", "fvg_gap", p)
    lock("fvg_gap", "fvg_min_gap_pct")

    # 2 path mode
    print("\n--- 2 FVG path ---", flush=True)
    for mode, flags in [
        ("fvg_or_mom", {"smc_orb_path_mode": "fvg_or_mom", "smc_orb_require_fvg": False, "smc_orb_require_ema_momentum": False}),
        ("fvg_only", {"smc_orb_path_mode": "fvg_only", "smc_orb_require_fvg": True, "smc_orb_require_ema_momentum": False}),
        ("mom_only", {"smc_orb_path_mode": "mom_only", "smc_orb_require_fvg": False, "smc_orb_require_ema_momentum": True}),
        ("fvg_preferred", {"smc_orb_path_mode": "fvg_preferred", "smc_orb_require_fvg": False, "smc_orb_require_ema_momentum": False}),
    ]:
        p = deepcopy(work)
        p.update(flags)
        ev(f"path_{mode}", "path", p)
    lock("path", "smc_orb_path_mode", "smc_orb_require_fvg", "smc_orb_require_ema_momentum")

    # 3 FVG retest quality
    print("\n--- 3 FVG retest ---", flush=True)
    for mode in ["touch", "enter", "mid", "reject"]:
        p = deepcopy(work)
        p["smc_orb_fvg_retest_mode"] = mode
        ev(f"retest_{mode}", "retest", p)
    lock("retest", "smc_orb_fvg_retest_mode")

    # 4 OR pad (fraction of OR mid)
    print("\n--- 4 OR pad ---", flush=True)
    pads = [0.0, 0.0002, 0.0004, 0.0005, 0.0006, 0.0008, 0.0010, 0.0012, 0.0015, 0.0020]
    if QUICK:
        pads = [0.0, 0.0004, 0.0008, 0.0012, 0.0020]
    for pad in pads:
        p = deepcopy(work)
        p["smc_orb_pad_pct"] = float(pad)
        ev(f"pad_{pad}", "pad", p)
    lock("pad", "smc_orb_pad_pct")

    # 5 entry buffer (zone pad multiplier in _in_zone)
    print("\n--- 5 Entry buffer ---", flush=True)
    bufs = [0.0, 0.02, 0.04, 0.05, 0.07, 0.08, 0.10, 0.12, 0.15, 0.20]
    if QUICK:
        bufs = [0.0, 0.05, 0.08, 0.12, 0.20]
    for b in bufs:
        p = deepcopy(work)
        p["entry_buffer_pct"] = float(b)
        ev(f"buf_{b}", "buffer", p)
    lock("buffer", "entry_buffer_pct")

    # 6 breakout
    print("\n--- 6 Breakout ---", flush=True)
    for label, flags in [
        ("off", {"smc_orb_require_breakout": False, "smc_orb_breakout_pad_pct": 0.0}),
        ("hard", {"smc_orb_require_breakout": True, "smc_orb_breakout_pad_pct": 0.0}),
        ("hard_buf", {"smc_orb_require_breakout": True, "smc_orb_breakout_pad_pct": float(work.get("entry_buffer_pct") or 0.12) / 100.0}),
    ]:
        p = deepcopy(work)
        p.update(flags)
        ev(f"bo_{label}", "breakout", p)
    lock("breakout", "smc_orb_require_breakout", "smc_orb_breakout_pad_pct")

    # 7 momentum / EMA sep
    print("\n--- 7 Momentum / EMA sep ---", flush=True)
    for on in [False, True]:
        p = deepcopy(work)
        p["smc_orb_require_ema_momentum"] = on
        ev(f"ema_mom_{on}", "ema_mom", p)
    for on in [False, True]:
        p = deepcopy(work)
        p["smc_orb_require_momentum"] = on
        p["smc_orb_momentum_mode"] = "two_bar" if on else "off"
        ev(f"bar_mom_{on}", "bar_mom", p)
    for sep in [0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.07, 0.10]:
        p = deepcopy(work)
        p["smc_orb_ema_sep_pct"] = float(sep)
        ev(f"ema_sep_{sep}", "ema_sep", p)
    lock("ema_mom", "smc_orb_require_ema_momentum")
    lock("bar_mom", "smc_orb_require_momentum", "smc_orb_momentum_mode")
    lock("ema_sep", "smc_orb_ema_sep_pct")

    # 8 rejection
    print("\n--- 8 Rejection ---", flush=True)
    for body in [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70]:
        p = deepcopy(work)
        p["smc_orb_reject_body_min"] = float(body)
        ev(f"body_{body}", "rej_body", p)
    for wick in [0.20, 0.25, 0.28, 0.30, 0.35, 0.40]:
        p = deepcopy(work)
        p["smc_orb_reject_wick_min"] = float(wick)
        ev(f"wick_{wick}", "rej_wick", p)
    for mode in ["body_only", "wick_only", "body_or_wick", "both"]:
        p = deepcopy(work)
        p["smc_orb_reject_mode"] = mode
        ev(f"rej_{mode}", "rej_mode", p)
    lock("rej_body", "smc_orb_reject_body_min")
    lock("rej_wick", "smc_orb_reject_wick_min")
    lock("rej_mode", "smc_orb_reject_mode")

    # 9 MTF bias / structure
    print("\n--- 9 Bias / structure ---", flush=True)
    for mode in ["block_opposite", "require_aligned", "aligned_5m"]:
        p = deepcopy(work)
        p["smc_orb_bias_mode"] = mode
        ev(f"bias_{mode}", "bias", p)
    for req in [False, True]:
        p = deepcopy(work)
        p["smc_orb_require_structure"] = req
        ev(f"struct_{req}", "structure", p)
    lock("bias", "smc_orb_bias_mode")
    lock("structure", "smc_orb_require_structure")

    # 10 RSI
    print("\n--- 10 RSI ---", flush=True)
    p = deepcopy(work)
    p["smc_orb_rsi_enabled"] = False
    ev("rsi_off", "rsi_on", p)
    p = deepcopy(work)
    p["smc_orb_rsi_enabled"] = True
    ev("rsi_on", "rsi_on", p)
    for lo, hi in [(45, 65), (48, 65), (50, 65), (50, 68), (52, 66), (52, 68), (54, 68), (55, 70), (40, 70)]:
        p = deepcopy(work)
        p.update({"smc_orb_rsi_enabled": True, "smc_orb_rsi_call_min": lo, "smc_orb_rsi_call_max": hi})
        ev(f"call_{lo}_{hi}", "call_rsi", p)
    for lo, hi in [(32, 52), (34, 52), (34, 50), (35, 55), (36, 54), (38, 54), (38, 56), (40, 55), (30, 60)]:
        p = deepcopy(work)
        p.update({"smc_orb_rsi_enabled": True, "smc_orb_rsi_put_min": lo, "smc_orb_rsi_put_max": hi})
        ev(f"put_{lo}_{hi}", "put_rsi", p)
    for on in [False, True]:
        p = deepcopy(work)
        p["smc_orb_rsi_slope"] = on
        ev(f"slope_{on}", "rsi_slope", p)
    if best("rsi_on") and best("rsi_on")["params"].get("smc_orb_rsi_enabled") is False:
        work["smc_orb_rsi_enabled"] = False
        print("LOCK rsi: OFF", flush=True)
    else:
        work["smc_orb_rsi_enabled"] = True
        lock("call_rsi", "smc_orb_rsi_call_min", "smc_orb_rsi_call_max")
        lock("put_rsi", "smc_orb_rsi_put_min", "smc_orb_rsi_put_max")
    lock("rsi_slope", "smc_orb_rsi_slope")

    # 11 volume
    print("\n--- 11 Volume ---", flush=True)
    vols = [0.0, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35, 1.50]
    if QUICK:
        vols = [0.0, 0.95, 1.10, 1.20, 1.35]
    for v in vols:
        p = deepcopy(work)
        p["volume_min"] = float(v)
        ev(f"vol_{v}", "volume", p)
    lock("volume", "volume_min")

    # 12-14 stop / target / trail
    print("\n--- 12-14 Stop/Target/Trail ---", flush=True)
    stops = [0.60, 0.70, 0.80, 0.90, 1.00, 1.10, 1.20, 1.30, 1.40, 1.50, 1.75]
    tgts = [0.80, 1.00, 1.20, 1.30, 1.40, 1.50, 1.60, 1.70, 1.80, 2.00, 2.20, 2.50]
    trails = [0.0, 0.50, 0.60, 0.75, 0.90, 1.00, 1.25, 1.50]
    if QUICK:
        stops = [0.80, 1.00, 1.20, 1.50]
        tgts = [1.20, 1.40, 1.60, 1.80, 2.00]
        trails = [0.0, 0.75, 1.00]
    for s in stops:
        p = deepcopy(work)
        p["stop_atr_mult"] = float(s)
        p.pop("smc_orb_stop_pts", None)
        ev(f"sl_{s}", "stop", p)
    for t in tgts:
        p = deepcopy(work)
        p["target_atr_mult"] = float(t)
        p.pop("smc_orb_target_pts", None)
        ev(f"tp_{t}", "target", p)
    lock("stop", "stop_atr_mult")
    lock("target", "target_atr_mult")
    work.pop("smc_orb_stop_pts", None)
    work.pop("smc_orb_target_pts", None)

    sl_c = sorted([r for r in rows if r["group"] == "stop" and r["metrics"]["trades"] >= 3], key=lambda r: r["score"], reverse=True)[:3]
    tg_c = sorted([r for r in rows if r["group"] == "target" and r["metrics"]["trades"] >= 3], key=lambda r: r["score"], reverse=True)[:3]
    for a, b in product(sl_c, tg_c):
        p = deepcopy(work)
        p["stop_atr_mult"] = a["params"]["stop_atr_mult"]
        p["target_atr_mult"] = b["params"]["target_atr_mult"]
        ev(f"rr_{p['stop_atr_mult']}_{p['target_atr_mult']}", "rr", p)
    lock("rr", "stop_atr_mult", "target_atr_mult")

    for tr in trails:
        p = deepcopy(work)
        p["trailing_atr_mult"] = float(tr)
        ev(f"trail_{tr}", "trail", p)
    lock("trail", "trailing_atr_mult")

    # 15 max hold
    print("\n--- 15 Max hold ---", flush=True)
    holds = [4, 5, 6, 8, 10, 12, 14, 16, 20]
    if QUICK:
        holds = [6, 8, 10, 12, 16]
    for h in holds:
        p = deepcopy(work)
        p["max_hold_bars"] = int(h)
        ev(f"hold_{h}", "hold", p)
    lock("hold", "max_hold_bars")

    # 16 entry window
    print("\n--- 16 Entry window ---", flush=True)
    for start in [9 * 60 + 25, 9 * 60 + 30, 9 * 60 + 35, 9 * 60 + 40]:
        p = deepcopy(work)
        p["smc_orb_entry_start_min"] = start
        ev(f"start_{start}", "start", p)
    for cut in [10 * 60 + 15, 10 * 60 + 30, 10 * 60 + 45, 11 * 60]:
        p = deepcopy(work)
        p["smc_orb_entry_cutoff_min"] = cut
        ev(f"cut_{cut}", "cutoff", p)
    lock("start", "smc_orb_entry_start_min")
    lock("cutoff", "smc_orb_entry_cutoff_min")

    # 17 scan / between
    print("\n--- 17 Scan / spacing ---", flush=True)
    for s in [1, 2, 3, 4, 5]:
        p = deepcopy(work)
        p["smc_entry_scan_every"] = s
        ev(f"scan_{s}", "scan", p)
    for m in [3, 4, 5, 6, 8, 10, 12, 15]:
        p = deepcopy(work)
        p["smc_min_bars_between"] = m
        ev(f"between_{m}", "between", p)
    lock("scan", "smc_entry_scan_every")
    lock("between", "smc_min_bars_between")

    # 18 regime filter (report only; lock if clearly better with enough trades)
    print("\n--- 18 Regime filter ---", flush=True)
    set_regime_filter(None)
    ev("regime_all", "regime", deepcopy(work))
    set_regime_filter({"TRENDING_UP", "TRENDING_DOWN"})
    ev("regime_trend", "regime", deepcopy(work))
    set_regime_filter({"TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"})
    ev("regime_trend_hv", "regime", deepcopy(work))
    set_regime_filter(None)

    # Stability around work
    print("\n--- Stability ---", flush=True)
    for dg in [-0.10, -0.05, 0.0, 0.05, 0.10]:
        p = deepcopy(work)
        p["fvg_min_gap_pct"] = max(0.008, float(work["fvg_min_gap_pct"]) + dg)
        ev(f"stab_gap_{p['fvg_min_gap_pct']:.3f}", "stability", p)
    for dp in [-0.0002, 0.0, 0.0002]:
        p = deepcopy(work)
        p["smc_orb_pad_pct"] = max(0.0, float(work["smc_orb_pad_pct"]) + dp)
        ev(f"stab_pad_{p['smc_orb_pad_pct']}", "stability", p)
    for ds in [-0.1, 0.0, 0.1]:
        p = deepcopy(work)
        p["stop_atr_mult"] = max(0.5, float(work["stop_atr_mult"]) + ds)
        ev(f"stab_sl_{p['stop_atr_mult']}", "stability", p)
    for dt in [-0.2, 0.0, 0.2]:
        p = deepcopy(work)
        p["target_atr_mult"] = max(0.8, float(work["target_atr_mult"]) + dt)
        ev(f"stab_tp_{p['target_atr_mult']}", "stability", p)

    # Combos
    print("\n--- Combos / WF ---", flush=True)
    combos = [deepcopy(base), deepcopy(work)]
    for d_sl, d_tg, d_tr in product([-0.1, 0.0, 0.1], [-0.2, 0.0, 0.2], [0.0]):
        p = deepcopy(work)
        p["stop_atr_mult"] = max(0.5, float(p["stop_atr_mult"]) + d_sl)
        p["target_atr_mult"] = max(0.8, float(p["target_atr_mult"]) + d_tg)
        combos.append(p)
    seen = set()
    unique = []
    for p in combos:
        key = json.dumps({k: p.get(k) for k in sorted(p)}, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)

    combo_train = [ev(f"combo_{i}", "combo", p) for i, p in enumerate(unique)]
    top = sorted(
        [r for r in combo_train if r["metrics"]["trades"] >= MIN_TRADES and r["metrics"]["expectancy"] > 0],
        key=lambda r: r["score"],
        reverse=True,
    )[:8]
    if not top:
        top = sorted(combo_train, key=lambda r: r["score"], reverse=True)[:5]

    val_rows = []
    for tr in top:
        vr = ev(tr["label"] + "_val", "combo_val", tr["params"], dataset="val")
        val_rows.append({**vr, "train_score": tr["score"]})

    recommended = None
    if val_rows:
        recommended = sorted(
            val_rows,
            key=lambda r: (
                1 if r["metrics"]["expectancy"] > 0 else 0,
                1 if r["metrics"]["win_rate"] >= base_train["win_rate"] else 0,
                r["score"],
                r.get("train_score", 0),
            ),
            reverse=True,
        )[0]

    rec_oos = rec_full = None
    if recommended:
        print("\n--- OOS + Full ---", flush=True)
        rec_oos = ev("recommended_oos", "oos", recommended["params"], dataset="oos")
        rec_full = ev("recommended_full", "full", recommended["params"], dataset="full")

    eligible = [r for r in rows if r["dataset"] == "train" and r["metrics"]["trades"] >= MIN_TRADES]
    ranked = sorted(eligible, key=lambda r: r["score"], reverse=True)

    picks = {
        g: best(g)
        for g in [
            "fvg_gap", "path", "retest", "pad", "buffer", "breakout", "ema_mom", "bar_mom", "ema_sep",
            "rej_body", "rej_wick", "rej_mode", "bias", "structure", "call_rsi", "put_rsi", "rsi_slope",
            "volume", "stop", "target", "rr", "trail", "hold", "start", "cutoff", "scan", "between",
        ]
    }

    report = {
        "strategy": STRATEGY_CODE,
        "data_source": source,
        "date_range": {"from": fr, "to": to},
        "bars": len(df),
        "fvg_gap_units": "gap/mid*100 >= fvg_min_gap_pct",
        "walk_forward": {"train": len(train), "val": len(val), "oos": len(oos)},
        "baseline": {"params": base, "full": base_full, "train": base_train, "val": base_val, "oos": base_oos},
        "ofat_best": {
            k: ({"label": v["label"], "score": v["score"], "metrics": v["metrics"], "params": v["params"]} if v else None)
            for k, v in picks.items()
        },
        "working_params": work,
        "top10_train": ranked[:10],
        "recommended": recommended,
        "recommended_oos": rec_oos,
        "recommended_full": rec_full,
        "notes": [
            "ORB minutes structurally fixed at 15 via prepare_mtf_frames session_orbs — not OFAT'd.",
            "Primary objective: improve win rate with positive expectancy / PF / controlled DD.",
            "Do not modify SCALP-SMC-006 Bank defaults.",
        ],
    }
    out = os.environ.get("REPORT_PATH", "/tmp/optimize_scalp_smc003_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote {out}", flush=True)
    print("\n=== TOP 10 TRAIN ===", flush=True)
    for i, r in enumerate(ranked[:10], 1):
        m = r["metrics"]
        print(
            f"{i:2}. [{r['group']}] {r['label']} sc={r['score']} WR={m['win_rate']}% "
            f"PF={m['profit_factor']} tr={m['trades']} PnL={m['total_pnl']} DD={m['max_drawdown']}",
            flush=True,
        )
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
