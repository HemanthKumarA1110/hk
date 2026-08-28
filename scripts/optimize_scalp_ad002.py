#!/usr/bin/env python3
"""SCALP-AD-002 (VWAP Bounce) OFAT + walk-forward — Nifty 50.

Uses existing run_strategy_backtest. Does not modify strategy defaults.

    PYTHONUNBUFFERED=1 python /app/scripts/optimize_scalp_ad002.py
"""

from __future__ import annotations

import json
import os
import pickle
import sys
from copy import deepcopy
from itertools import product
from typing import Any

STRATEGY_CODE = "SCALP-AD-002"
INSTRUMENT_KEY = "nifty50"
MIN_TRADES = int(os.environ.get("MIN_TRADES", "5"))
CANDLE_CACHE = os.environ.get("CANDLE_CACHE", "/tmp/bt004_candles.pkl")
QUICK = os.environ.get("QUICK", "0") == "1"

_SESSION = "both"
_REGIME_ALLOW: set[str] | None = None


def baseline_params() -> dict[str, Any]:
    from trading_shared.strategies.scalping_desk.vwap_bounce_tuning import VWAP_BOUNCE_NIFTY_DEFAULTS

    return dict(VWAP_BOUNCE_NIFTY_DEFAULTS)


def get_candles():
    with open(CANDLE_CACHE, "rb") as f:
        p = pickle.load(f)
    return p["df"], p["source"], p["from_date"], p["to_date"]


def install_patches() -> None:
    import trading_shared.strategies.scalping_desk.battle_tested_scalp as bts
    import trading_shared.strategies.scalping_desk.strategies as strat

    orig = strat.evaluate_vwap_bounce

    def wrapped(df, timeframe, option_chain, lot_size, **kwargs):
        signal = orig(df, timeframe, option_chain, lot_size, **kwargs)
        if signal is None:
            return None
        ts = df.iloc[-1].get("timestamp") if len(df) else None
        ist = bts._to_ist(ts)
        if ist is not None and _SESSION != "both":
            minutes = ist.hour * 60 + ist.minute
            morning = 9 * 60 + 20 <= minutes <= 10 * 60 + 30
            afternoon = 13 * 60 + 30 <= minutes <= 14 * 60 + 45
            if _SESSION == "morning" and not morning:
                return None
            if _SESSION == "afternoon" and not afternoon:
                return None
        if _REGIME_ALLOW is not None:
            try:
                from trading_shared.strategies.scalping_desk.market_context import detect_regime_from_candles

                reg = str(detect_regime_from_candles(df.tail(60)).value)
                if reg.upper() not in {x.upper() for x in _REGIME_ALLOW}:
                    return None
            except Exception:
                pass
        return signal

    strat.evaluate_vwap_bounce = wrapped
    strat.STRATEGY_REGISTRY["vwap_bounce"]["evaluate"] = wrapped


def set_filters(*, session: str = "both", regimes: set[str] | None = None) -> None:
    global _SESSION, _REGIME_ALLOW
    _SESSION = session
    _REGIME_ALLOW = regimes


def run_bt(candles, lot, capital, vb):
    from trading_shared.strategies.scalping_desk.backtest import run_strategy_backtest

    return run_strategy_backtest(
        candles, "1m", lot, capital,
        strategy_code=STRATEGY_CODE, instrument_key=INSTRUMENT_KEY,
        params={"vwap_bounce": vb},
        max_loss_per_day=5000, max_trades_per_day=5,
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
        "call_wr": wr(calls),
        "put_n": len(puts),
        "put_wr": wr(puts),
        "morning_n": len(morning),
        "morning_wr": wr(morning),
        "afternoon_n": len(afternoon),
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


def score(m, ref_n=20):
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


def main() -> int:
    import trading_shared.strategies.scalping_desk.backtest as bt
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

    bt.MAX_BACKTEST_BARS = 40000
    install_patches()
    set_filters()

    capital = 100000.0
    lot = int(INSTRUMENTS[INSTRUMENT_KEY]["lot_size"])
    df, source, fr, to = get_candles()
    train, val, oos = split_wf(df)
    base = baseline_params()
    print(f"=== {STRATEGY_CODE} bars={len(df)} {fr}→{to} QUICK={QUICK} ===", flush=True)

    print("\n--- BASELINE full ---", flush=True)
    base_m = metrics(run_bt(df, lot, capital, base), df)
    print(json.dumps({k: base_m[k] for k in (
        "trades", "win_rate", "profit_factor", "expectancy", "total_pnl", "max_drawdown",
        "winning_trades", "losing_trades", "avg_win", "avg_loss",
        "max_consec_wins", "max_consec_losses",
        "call_n", "call_wr", "put_n", "put_wr", "morning_n", "morning_wr", "afternoon_n", "afternoon_wr",
    )}, indent=2), flush=True)

    probe = deepcopy(base)
    # Baseline is extremely sparse inside battle windows on this sample (often 0 trades).
    # OFAT uses a session-aligned searchable probe: % VWAP band + slightly wider RSI + candle off.
    probe.update(
        {
            "vb_near_atr_mult": 0.0,
            "vb_near_pct": 0.30,
            "vb_candle_mode": "off",
            "vb_call_prev_rsi_max": 48,
            "vb_call_rsi_min": 42,
            "vb_call_rsi_max": 62,
            "vb_put_prev_rsi_min": 52,
            "vb_put_rsi_min": 38,
            "vb_put_rsi_max": 58,
        }
    )
    print("\n--- PROBE (OFAT reference) ---", flush=True)
    probe_m = metrics(run_bt(train, lot, capital, probe), train)
    print(json.dumps({k: probe_m[k] for k in ("trades", "win_rate", "profit_factor", "expectancy", "total_pnl", "max_drawdown")}, indent=2), flush=True)
    if probe_m["trades"] < max(3, MIN_TRADES // 2):
        print("Probe still too thin — widening further", flush=True)
        probe.update({"vb_near_pct": 0.40, "vb_call_prev_rsi_max": 50, "vb_put_prev_rsi_min": 50})
        probe_m = metrics(run_bt(train, lot, capital, probe), train)
        print(json.dumps({k: probe_m[k] for k in ("trades", "win_rate", "profit_factor", "expectancy", "total_pnl")}, indent=2), flush=True)

    rows = []
    ref_n = max(probe_m["trades"], base_m["trades"], 12)

    def ev(label, group, vb, frame=None, dataset="train"):
        data = frame if frame is not None else train
        m = metrics(run_bt(data, lot, capital, vb), data)
        sc = score(m, ref_n=ref_n)
        row = {"label": label, "group": group, "dataset": dataset, "params": dict(vb), "metrics": m, "score": round(sc, 2)}
        rows.append(row)
        print(
            f"{group:10} {label:34} n={m['trades']:>3} WR={m['win_rate']:>6}% "
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
            return None
        return max(pool, key=lambda r: (r["score"], r["metrics"]["win_rate"], r["metrics"]["trades"]))

    # 1 VWAP proximity ATR
    print("\n--- 1 VWAP ATR ---", flush=True)
    atrs = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60]
    if QUICK:
        atrs = [0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
    for a in atrs:
        o = deepcopy(probe)
        o.update({"vb_near_atr_mult": float(a), "vb_near_pct": 0.0})
        ev(f"near_atr_{a}", "near_atr", o)

    # 1b percent
    print("\n--- 1b VWAP pct ---", flush=True)
    pcts = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]
    if QUICK:
        pcts = [0.10, 0.15, 0.20, 0.25, 0.30]
    for p in pcts:
        o = deepcopy(probe)
        o.update({"vb_near_atr_mult": 0.0, "vb_near_pct": float(p)})
        ev(f"near_pct_{p}", "near_pct", o)

    # Lock near from best of atr/pct
    b_atr, b_pct = best("near_atr"), best("near_pct")
    near_pick = max([x for x in (b_atr, b_pct) if x], key=lambda r: r["score"], default=None)
    if near_pick:
        probe["vb_near_atr_mult"] = float(near_pick["params"]["vb_near_atr_mult"])
        probe["vb_near_pct"] = float(near_pick["params"]["vb_near_pct"])
        print(f"LOCK near atr={probe['vb_near_atr_mult']} pct={probe['vb_near_pct']}", flush=True)

    # 2 CALL RSI
    print("\n--- 2 CALL RSI ---", flush=True)
    call_prev = [38, 40, 42, 43, 44, 45, 46, 48, 50]
    call_rng = [(42, 54), (43, 55), (44, 56), (45, 57), (45, 58), (46, 58), (46, 60), (48, 60), (48, 62)]
    if QUICK:
        call_prev = [40, 42, 45, 48]
        call_rng = [(43, 55), (45, 58), (46, 60), (48, 62)]
    for prev in call_prev:
        o = deepcopy(probe)
        o["vb_call_prev_rsi_max"] = int(prev)
        ev(f"call_prev_{prev}", "call_prev", o)
    for lo, hi in call_rng:
        o = deepcopy(probe)
        o.update({"vb_call_rsi_min": lo, "vb_call_rsi_max": hi})
        ev(f"call_rsi_{lo}_{hi}", "call_rsi", o)
    bp, br = best("call_prev"), best("call_rsi")
    if bp:
        probe["vb_call_prev_rsi_max"] = int(bp["params"]["vb_call_prev_rsi_max"])
    if br:
        probe["vb_call_rsi_min"] = int(br["params"]["vb_call_rsi_min"])
        probe["vb_call_rsi_max"] = int(br["params"]["vb_call_rsi_max"])

    # 3 PUT RSI
    print("\n--- 3 PUT RSI ---", flush=True)
    put_prev = [52, 54, 55, 56, 57, 58, 60, 62]
    put_rng = [(40, 52), (41, 53), (42, 54), (42, 55), (43, 55), (44, 56), (44, 58), (45, 58)]
    if QUICK:
        put_prev = [54, 55, 58, 60]
        put_rng = [(42, 55), (44, 56), (44, 58), (45, 58)]
    for prev in put_prev:
        o = deepcopy(probe)
        o["vb_put_prev_rsi_min"] = int(prev)
        ev(f"put_prev_{prev}", "put_prev", o)
    for lo, hi in put_rng:
        o = deepcopy(probe)
        o.update({"vb_put_rsi_min": lo, "vb_put_rsi_max": hi})
        ev(f"put_rsi_{lo}_{hi}", "put_rsi", o)
    pp, pr = best("put_prev"), best("put_rsi")
    if pp:
        probe["vb_put_prev_rsi_min"] = int(pp["params"]["vb_put_prev_rsi_min"])
    if pr:
        probe["vb_put_rsi_min"] = int(pr["params"]["vb_put_rsi_min"])
        probe["vb_put_rsi_max"] = int(pr["params"]["vb_put_rsi_max"])

    # 4 RSI turn
    print("\n--- 4 RSI turn ---", flush=True)
    for t in [0, 1, 2, 3, 4, 5]:
        o = deepcopy(probe)
        o["vb_rsi_turn_min"] = float(t)
        ev(f"turn_{t}", "turn", o)
    bt_ = best("turn")
    if bt_:
        probe["vb_rsi_turn_min"] = float(bt_["params"]["vb_rsi_turn_min"])

    # 5 Target
    print("\n--- 5 Target ---", flush=True)
    tgts = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.70, 0.80, 1.00]
    # map display mult (user) to effective atr mult: user target_mult * 0.55
    # We store vb_target_atr_mult as effective ATR mult (baseline 0.2475 = 0.45*0.55)
    if QUICK:
        tgts = [0.20, 0.25, 0.30, 0.35, 0.45, 0.55, 0.70]
    for tm in tgts:
        o = deepcopy(probe)
        o["vb_target_atr_mult"] = float(tm) * 0.55  # convert user-style mult → effective
        ev(f"tgt_mult_{tm}", "target", o)
    for floor in [5, 6, 8, 10, 12, 15]:
        o = deepcopy(probe)
        o["vb_min_target_pts"] = float(floor)
        ev(f"tgt_floor_{floor}", "tgt_floor", o)
    btgt = best("target")
    if btgt:
        probe["vb_target_atr_mult"] = float(btgt["params"]["vb_target_atr_mult"])

    # 6 Stop
    print("\n--- 6 Stop ---", flush=True)
    stops = [0.60, 0.70, 0.80, 0.90, 0.95, 1.00, 1.10, 1.20, 1.30, 1.40, 1.50]
    if QUICK:
        stops = [0.70, 0.80, 0.95, 1.10, 1.25, 1.40]
    for sm in stops:
        o = deepcopy(probe)
        o["vb_stop_atr_mult"] = float(sm) * 1.2  # user stop_mult → effective
        ev(f"stop_mult_{sm}", "stop", o)
    bstop = best("stop")
    if bstop:
        probe["vb_stop_atr_mult"] = float(bstop["params"]["vb_stop_atr_mult"])

    # 7 SL/TP combo
    print("\n--- 7 SL/TP combo ---", flush=True)
    sm_c = sorted({probe["vb_stop_atr_mult"] / 1.2, 0.80, 0.95, 1.10, 1.25})
    tm_c = sorted({probe["vb_target_atr_mult"] / 0.55, 0.30, 0.40, 0.50, 0.60, 0.70})
    if QUICK:
        sm_c = sorted({probe["vb_stop_atr_mult"] / 1.2, 0.95, 1.10})
        tm_c = sorted({probe["vb_target_atr_mult"] / 0.55, 0.35, 0.45, 0.60})
    for sm, tm in product(sm_c, tm_c):
        o = deepcopy(probe)
        o.update({"vb_stop_atr_mult": float(sm) * 1.2, "vb_target_atr_mult": float(tm) * 0.55})
        ev(f"rr_{sm:.2f}_{tm:.2f}", "rr", o)
    brr = best("rr")
    if brr:
        probe["vb_stop_atr_mult"] = float(brr["params"]["vb_stop_atr_mult"])
        probe["vb_target_atr_mult"] = float(brr["params"]["vb_target_atr_mult"])

    # 8 Hold
    print("\n--- 8 Hold ---", flush=True)
    for h in [3, 4, 5, 6, 7, 8, 10, 12, 15]:
        o = deepcopy(probe)
        o["vb_max_hold_bars"] = int(h)
        ev(f"hold_{h}", "hold", o)
    bhold = best("hold")
    if bhold:
        probe["vb_max_hold_bars"] = int(bhold["params"]["vb_max_hold_bars"])

    # 9 Candle / side / close loc
    print("\n--- 9 Candle / side ---", flush=True)
    for mode in ["color", "off", "body30", "body40", "body50", "body60"]:
        o = deepcopy(probe)
        o["vb_candle_mode"] = mode
        ev(f"candle_{mode}", "candle", o)
    for mode in ["touch", "prev", "cross"]:
        o = deepcopy(probe)
        o["vb_side_mode"] = mode
        ev(f"side_{mode}", "side", o)
    for loc in [0.0, 0.50, 0.60, 0.70, 0.80]:
        o = deepcopy(probe)
        o["vb_close_loc_pct"] = float(loc)
        ev(f"close_loc_{loc}", "close_loc", o)
    bc, bs, bl = best("candle"), best("side"), best("close_loc")
    if bc:
        probe["vb_candle_mode"] = bc["params"]["vb_candle_mode"]
    if bs:
        probe["vb_side_mode"] = bs["params"]["vb_side_mode"]
    if bl and bl["score"] >= (best("close_loc") and rows and 0):
        # only keep close_loc if clearly helps vs 0
        zero = next((r for r in rows if r["label"] == "close_loc_0.0"), None)
        if zero is None or bl["score"] >= zero["score"] + 3:
            probe["vb_close_loc_pct"] = float(bl["params"]["vb_close_loc_pct"])
        else:
            probe["vb_close_loc_pct"] = 0.0

    # 10 Session / regime
    print("\n--- 10 Session / regime ---", flush=True)
    for sess in ("both", "morning", "afternoon"):
        set_filters(session=sess)
        ev(f"sess_{sess}", "session", deepcopy(probe))
    set_filters()
    for name, regs in (
        ("all", None),
        ("ranging", {"RANGING"}),
        ("ranging_lv", {"RANGING", "LOW_VOLATILITY"}),
        ("lv", {"LOW_VOLATILITY"}),
    ):
        set_filters(regimes=regs)
        ev(f"reg_{name}", "regime", deepcopy(probe))
    set_filters()

    # Combos
    print("\n--- Combos ---", flush=True)
    combos = [
        ("A_probe", deepcopy(probe)),
        ("B_baseline", deepcopy(base)),
    ]
    c = deepcopy(probe)
    c.update({"vb_near_atr_mult": 0.25, "vb_near_pct": 0.0})
    combos.append(("C_near25", c))
    c = deepcopy(probe)
    c.update({"vb_candle_mode": "color", "vb_rsi_turn_min": 0.0})
    combos.append(("D_color_noturn", c))
    c = deepcopy(base)
    c.update({
        "vb_near_atr_mult": float(probe["vb_near_atr_mult"]),
        "vb_near_pct": float(probe["vb_near_pct"]),
        "vb_call_prev_rsi_max": int(probe["vb_call_prev_rsi_max"]),
        "vb_call_rsi_min": int(probe["vb_call_rsi_min"]),
        "vb_call_rsi_max": int(probe["vb_call_rsi_max"]),
        "vb_put_prev_rsi_min": int(probe["vb_put_prev_rsi_min"]),
        "vb_put_rsi_min": int(probe["vb_put_rsi_min"]),
        "vb_put_rsi_max": int(probe["vb_put_rsi_max"]),
    })
    combos.append(("E_rsi_near_only", c))
    c = deepcopy(probe)
    c.update({"vb_stop_atr_mult": 1.14, "vb_target_atr_mult": 0.2475, "vb_max_hold_bars": 8})
    combos.append(("F_probe_base_risk", c))

    seen = set()
    for name, orb in combos:
        key = json.dumps(orb, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        ev(name, "combo", orb)

    # Stability
    print("\n--- Stability ---", flush=True)
    na = float(probe["vb_near_atr_mult"])
    if na > 0:
        for a in sorted({max(0.05, na + d) for d in (-0.05, -0.02, 0, 0.02, 0.05)}):
            o = deepcopy(probe)
            o.update({"vb_near_atr_mult": float(a), "vb_near_pct": 0.0})
            ev(f"stab_atr_{a:.2f}", "stab", o)

    eligible = [
        r for r in rows
        if r["dataset"] == "train"
        and r["group"] in ("combo", "rr", "near_atr", "near_pct", "hold", "candle", "target", "stop")
        and r["metrics"]["trades"] >= MIN_TRADES
        and r["metrics"]["expectancy"] > 0
    ]
    ranked = sorted(eligible, key=lambda r: (r["score"], r["metrics"]["win_rate"], r["metrics"]["trades"]), reverse=True)
    extras = [r for r in rows if r["metrics"]["trades"] >= MIN_TRADES and r["metrics"]["expectancy"] > 0]
    top_pool = []
    seen_l = set()
    for r in sorted(ranked + extras, key=lambda r: (r["score"], r["metrics"]["win_rate"]), reverse=True):
        if r["label"] in seen_l:
            continue
        seen_l.add(r["label"])
        top_pool.append(r)

    rec = ranked[0] if ranked else (top_pool[0] if top_pool else None)
    if not rec:
        print("No viable recommendation", flush=True)
        return 1
    rec_params = deepcopy(rec["params"])

    # Prefer probe if close in score but more trades
    probe_row = next((r for r in rows if r["label"] == "A_probe"), None)
    if probe_row and probe_row["metrics"]["expectancy"] > 0 and probe_row["metrics"]["trades"] >= MIN_TRADES:
        if probe_row["score"] >= rec["score"] - 8 and probe_row["metrics"]["trades"] >= rec["metrics"]["trades"]:
            rec = probe_row
            rec_params = deepcopy(probe)

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

    # Reject obvious overfit: train WR>=95 with n<10 and val bad
    if (
        rec_train["metrics"]["trades"] < 10
        and rec_train["metrics"]["win_rate"] >= 95
        and rec_val["metrics"]["trades"] >= 3
        and rec_val["metrics"]["expectancy"] < 0
        and probe_row
        and probe_row["metrics"]["expectancy"] > 0
    ):
        print("NOTE: rejecting overfit; falling back to A_probe", flush=True)
        rec_params = deepcopy(probe)
        for label, frame, ds in [
            ("rec_train2", train, "train"),
            ("rec_val2", val, "val"),
            ("rec_oos2", oos, "oos"),
            ("rec_full2", df, "full"),
        ]:
            ev(label, "final", rec_params, frame=frame, dataset=ds)
        rec_train = next(r for r in rows if r["label"] == "rec_train2")
        rec_val = next(r for r in rows if r["label"] == "rec_val2")
        rec_oos = next(r for r in rows if r["label"] == "rec_oos2")
        rec_full = next(r for r in rows if r["label"] == "rec_full2")

    losses = [t for t in (run_bt(df, lot, capital, rec_params).get("trades") or []) if float(t.get("pnl") or 0) <= 0]
    autopsy = {"n": len(losses), "by_exit": {}}
    for t in losses:
        reason = str(t.get("exit_reason") or "?")
        autopsy["by_exit"][reason] = autopsy["by_exit"].get(reason, 0) + 1

    report = {
        "strategy": STRATEGY_CODE,
        "source": source,
        "date_range": {"from": fr, "to": to},
        "bars": len(df),
        "baseline_full": {"params": base, "metrics": base_m},
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
        "ofat_locked": probe,
    }
    out = os.environ.get("REPORT_PATH", "/tmp/optimize_scalp_ad002_report.json")
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
