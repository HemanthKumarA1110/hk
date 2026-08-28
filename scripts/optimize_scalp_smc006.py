#!/usr/bin/env python3
"""SCALP-SMC-006 lean OFAT + walk-forward (Bank Nifty).

Baseline already ~100% WR with few trades / tiny expectancy.
Priority: keep high WR, raise trade count + expectancy, validate OOS.

    PYTHONUNBUFFERED=1 python /app/scripts/optimize_scalp_smc006.py
"""

from __future__ import annotations

import asyncio
import json
import os
import pickle
import sys
from copy import deepcopy
from datetime import date, timedelta
from itertools import product
from typing import Any

STRATEGY_ID = "smc_orb_fvg"
STRATEGY_CODE = "SCALP-SMC-006"
INSTRUMENT_KEY = "banknifty"
BACKTEST_DAYS = int(os.environ.get("BACKTEST_DAYS", "60"))
MIN_TRADES = int(os.environ.get("MIN_TRADES", "5"))
CANDLE_CACHE = os.environ.get("CANDLE_CACHE", "/tmp/smc006_candles.pkl")


def baseline_params() -> dict[str, Any]:
    from trading_shared.strategies.scalping_desk.smc_orb_fvg_tuning import SMC_ORB_FVG_BANK_DEFAULTS

    p = dict(SMC_ORB_FVG_BANK_DEFAULTS)
    p.setdefault("smc_orb_pad_pct", 0.0008)
    p.setdefault("smc_orb_entry_start_min", 9 * 60 + 30)
    p.setdefault("smc_orb_fvg_mode", "or")
    p.setdefault("smc_orb_momentum_mode", "two_bar")
    p.setdefault("smc_orb_bias_mode", "current")
    p.setdefault("smc_orb_require_structure", False)
    p.setdefault("smc_orb_rsi_slope", False)
    p.setdefault("smc_orb_reject_body_min", 0.0)
    p.setdefault("smc_orb_ema_sep_pct", 0.0)
    p.setdefault("smc_orb_ema_strict", False)
    return p


def get_candles(user_id: int):
    for path in (CANDLE_CACHE, "/tmp/ad006_candles.pkl", "/tmp/ad005_candles.pkl"):
        if os.path.isfile(path) and os.environ.get("FORCE_RELOAD") != "1":
            with open(path, "rb") as f:
                payload = pickle.load(f)
            print(f"Loaded cache {path}: bars={len(payload['df']):,}", flush=True)
            if path != CANDLE_CACHE:
                with open(CANDLE_CACHE, "wb") as f:
                    pickle.dump(payload, f)
            return payload["df"], payload["source"], payload["from_date"], payload["to_date"]

    import trading_shared.strategies.scalping_desk.service as svc_mod
    from trading_shared.db.session import SessionLocal
    from trading_shared.strategies.scalping_desk.service import ScalpingDeskService

    svc_mod.BACKTEST_CHUNK_DELAY_SEC = 1.5
    to_date = date.today()
    from_date = (to_date - timedelta(days=BACKTEST_DAYS)).isoformat()
    db = SessionLocal()
    try:
        svc = ScalpingDeskService(db, user_id, INSTRUMENT_KEY)
        df, source, notes = asyncio.run(svc._load_desk_backtest_candles(from_date, to_date.isoformat(), "1m"))
        if notes:
            print("notes:", "; ".join(notes), flush=True)
    finally:
        db.close()
    payload = {"df": df, "source": source, "from_date": from_date, "to_date": to_date.isoformat()}
    with open(CANDLE_CACHE, "wb") as f:
        pickle.dump(payload, f)
    return df, source, from_date, to_date.isoformat()


def install_patches() -> None:
    import trading_shared.strategies.scalping_desk.smc_scalping_engine as eng
    from trading_shared.strategies.scalping_desk.battle_tested_scalp import _to_ist
    from trading_shared.strategies.scalping_desk.smc_scalping_engine import (
        SMCSetup,
        _in_zone,
        _rejection,
        _resolve_bias,
        detect_fvg,
        opening_range,
    )
    from trading_shared.strategies.scalping_desk.strategies import _two_bar_momentum

    def rejection_ok(row, direction: str, body_min: float) -> bool:
        if body_min <= 0:
            return _rejection(row, direction)
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        body = abs(c - o)
        rng = max(h - l, 0.01)
        if body / rng < body_min:
            return False
        return _rejection(row, direction)

    def momentum_ok(df1, direction: str, mode: str, atr: float, atr_mult: float) -> bool:
        if mode in ("off",):
            return True
        if mode in ("two_bar", "on"):
            return _two_bar_momentum(df1, direction)
        if len(df1) < 2:
            return False
        row, prev = df1.iloc[-1], df1.iloc[-2]
        if mode == "one_bar":
            return (float(row["close"]) > float(row["open"])) if direction == "CALL" else (float(row["close"]) < float(row["open"]))
        if mode == "two_close":
            if len(df1) < 3:
                return False
            a, b, c = float(df1.iloc[-3]["close"]), float(prev["close"]), float(row["close"])
            return (c > b > a) if direction == "CALL" else (c < b < a)
        if mode == "atr":
            return abs(float(row["close"]) - float(prev["close"])) >= atr * atr_mult and _two_bar_momentum(df1, direction)
        return _two_bar_momentum(df1, direction)

    def evaluate_patched(mtf, params: dict[str, Any]):
        df1 = mtf.df_1m
        if len(df1) < 20:
            return None
        orb = opening_range(df1, int(params.get("orb_minutes", 15)), mtf.session_orb)
        if not orb:
            return None
        or_range = float(orb["high"] - orb["low"])
        rmin = float(params.get("smc_orb_range_min") or 0)
        rmax = float(params.get("smc_orb_range_max") or 99999)
        if or_range < rmin:
            return None
        if params.get("smc_orb_skip_wide_or") and or_range > rmax:
            return None

        row = df1.iloc[-1]
        prev = df1.iloc[-2] if len(df1) >= 2 else row
        spot = float(row["close"])
        atr = float(row.get("atr") or spot * 0.002)
        if float(row.get("volume_ratio", 1)) < float(params.get("volume_min", 0)):
            return None

        ist = _to_ist(row.get("timestamp"))
        if ist is not None:
            minutes = ist.hour * 60 + ist.minute
            start = int(params.get("smc_orb_entry_start_min") or (9 * 60 + 30))
            cutoff = int(params.get("smc_orb_entry_cutoff_min") or (10 * 60 + 45))
            if minutes < start or minutes > cutoff:
                return None

        fvgs = detect_fvg(df1.tail(30), float(params.get("fvg_min_gap_pct", 0.008)))
        buffer = float(params.get("entry_buffer_pct", 0.12))
        bias_mode = str(params.get("smc_orb_bias_mode") or "current")
        if bias_mode == "align":
            if mtf.bias_15m == "neutral" or mtf.structure_5m not in ("neutral", mtf.bias_15m):
                return None
            bias = mtf.bias_15m
        elif bias_mode == "strong15":
            bias = mtf.bias_15m
            if bias == "neutral":
                return None
        else:
            bias = _resolve_bias(mtf)

        require_struct = bool(params.get("smc_orb_require_structure", False))
        pad_pct = float(params.get("smc_orb_pad_pct") if params.get("smc_orb_pad_pct") is not None else 0.0008)
        orb_pad = orb["mid"] * pad_pct
        fvg_mode = str(params.get("smc_orb_fvg_mode") or "or")
        require_breakout = bool(params.get("smc_orb_require_breakout", True))
        mom_mode = str(params.get("smc_orb_momentum_mode") or ("on" if params.get("smc_orb_require_momentum", True) else "off"))
        atr_mom = float(params.get("smc_orb_mom_atr_mult") or 0.1)
        call_lo = int(params.get("smc_orb_rsi_call_min") or 40)
        call_hi = int(params.get("smc_orb_rsi_call_max") or 70)
        put_lo = int(params.get("smc_orb_rsi_put_min") or 30)
        put_hi = int(params.get("smc_orb_rsi_put_max") or 60)
        rsi = float(row.get("rsi14", 50))
        prev_rsi = float(prev.get("rsi14", rsi))
        rsi_slope = bool(params.get("smc_orb_rsi_slope", False))
        body_min = float(params.get("smc_orb_reject_body_min") or 0.0)
        ema_sep = float(params.get("smc_orb_ema_sep_pct") or 0.0)
        ema_strict = bool(params.get("smc_orb_ema_strict", False))
        stop_pts = float(params["smc_orb_stop_pts"]) if params.get("smc_orb_stop_pts") is not None else atr * float(params.get("stop_atr_mult", 1.0))
        target_pts = float(params["smc_orb_target_pts"]) if params.get("smc_orb_target_pts") is not None else atr * float(params.get("target_atr_mult", 1.6))
        ema9 = float(row.get("ema9", spot))
        ema21 = float(row.get("ema21", spot))
        sep_ok = (abs(ema9 - ema21) / max(spot, 1) * 100) >= ema_sep if ema_sep > 0 else True

        if bias != "bearish" and spot > orb["high"] - orb_pad:
            if not (require_struct and mtf.structure_5m == "bearish"):
                bull_fvgs = [f for f in fvgs if f["type"] == "bullish"]
                fvg_hit = bool(bull_fvgs and _in_zone(spot, bull_fvgs[-1], buffer))
                mom_ema = (ema9 > ema21) if ema_strict else (ema9 >= ema21)
                momentum = spot > orb["mid"] and mom_ema and sep_ok
                breakout = spot > orb["high"]
                if fvg_mode == "fvg":
                    signal_ok = fvg_hit
                elif fvg_mode == "momentum":
                    signal_ok = momentum
                elif fvg_mode == "fvg_preferred":
                    signal_ok = fvg_hit or (momentum and _two_bar_momentum(df1, "CALL"))
                else:
                    signal_ok = fvg_hit or momentum
                if require_breakout and not breakout:
                    signal_ok = False
                if not momentum_ok(df1, "CALL", mom_mode, atr, atr_mom):
                    signal_ok = False
                if not (call_lo <= rsi <= call_hi):
                    signal_ok = False
                if rsi_slope and not (rsi > prev_rsi):
                    signal_ok = False
                if signal_ok and rejection_ok(row, "bullish", body_min):
                    zone = (bull_fvgs[-1]["bottom"], bull_fvgs[-1]["top"]) if bull_fvgs else (orb["high"], orb["high"] * 1.001)
                    return SMCSetup("smc_orb_fvg", "CALL", bias if bias != "neutral" else "bullish", zone, ["orb_breakout_up", "fvg_or_momentum"], round(stop_pts, 2), round(target_pts, 2))

        if bias != "bullish" and spot < orb["low"] + orb_pad:
            if require_struct and mtf.structure_5m == "bullish":
                return None
            bear_fvgs = [f for f in fvgs if f["type"] == "bearish"]
            fvg_hit = bool(bear_fvgs and _in_zone(spot, bear_fvgs[-1], buffer))
            mom_ema = (ema9 < ema21) if ema_strict else (ema9 <= ema21)
            momentum = spot < orb["mid"] and mom_ema and sep_ok
            breakout = spot < orb["low"]
            if fvg_mode == "fvg":
                signal_ok = fvg_hit
            elif fvg_mode == "momentum":
                signal_ok = momentum
            elif fvg_mode == "fvg_preferred":
                signal_ok = fvg_hit or (momentum and _two_bar_momentum(df1, "PUT"))
            else:
                signal_ok = fvg_hit or momentum
            if require_breakout and not breakout:
                signal_ok = False
            if not momentum_ok(df1, "PUT", mom_mode, atr, atr_mom):
                signal_ok = False
            if not (put_lo <= rsi <= put_hi):
                signal_ok = False
            if rsi_slope and not (rsi < prev_rsi):
                signal_ok = False
            if signal_ok and rejection_ok(row, "bearish", body_min):
                zone = (bear_fvgs[-1]["bottom"], bear_fvgs[-1]["top"]) if bear_fvgs else (orb["low"] * 0.999, orb["low"])
                return SMCSetup("smc_orb_fvg", "PUT", bias if bias != "neutral" else "bearish", zone, ["orb_breakout_down", "fvg_or_momentum"], round(stop_pts, 2), round(target_pts, 2))
        return None

    eng.evaluate_orb_fvg_setup = evaluate_patched
    eng.SMC_EVALUATORS["smc_orb_fvg"] = evaluate_patched


def run_bt(candles, lot, capital, params):
    from trading_shared.strategies.scalping_desk.smc_backtest import run_single_smc_backtest

    return run_single_smc_backtest(
        candles, STRATEGY_ID, lot, capital,
        instrument_key=INSTRUMENT_KEY, params=params,
        max_lots_per_trade=2, max_loss_per_day=5000, max_trades_per_day=5,
    )


def metrics(result, candles=None):
    from trading_shared.strategies.scalping_desk.market_context import detect_regime_from_candles

    trades = result.get("trades") or []
    n = int(result.get("total_trades") or 0)
    pnl = float(result.get("total_pnl") or 0)
    wr = float(result.get("win_rate") or 0)
    pf = float(result.get("profit_factor") or 0)
    dd = float(result.get("max_drawdown") or 0)
    avg_win = float(result.get("avg_profit_win") or 0)
    avg_loss = float(result.get("avg_loss_loss") or 0)
    wins = sum(1 for t in trades if float(t.get("pnl") or 0) > 0)
    expectancy = round(pnl / n, 2) if n else 0.0

    def subset(rows):
        if not rows:
            return None, 0
        w = sum(1 for t in rows if float(t.get("pnl") or 0) > 0)
        return round(w / len(rows) * 100, 2), len(rows)

    calls = [t for t in trades if str(t.get("signal_type")).upper() == "CALL"]
    puts = [t for t in trades if str(t.get("signal_type")).upper() == "PUT"]
    morning = []
    for t in trades:
        try:
            part = str(t.get("entry_time") or "")
            hhmm = part.split("T")[1][:5] if "T" in part else part.split(" ")[1][:5]
            h, m = map(int, hhmm.split(":"))
            mins = h * 60 + m
            if 9 * 60 <= mins <= 12 * 60:
                morning.append(t)
        except Exception:
            pass

    regimes = {}
    if candles is not None and trades and "timestamp" in candles.columns:
        ts_series = candles["timestamp"].astype(str)
        for t in trades:
            et = str(t.get("entry_time") or "")
            idx = ts_series[ts_series.str.startswith(et[:16])].index if et else []
            if len(idx) == 0:
                reg = "UNKNOWN"
            else:
                i = int(idx[-1])
                try:
                    reg = detect_regime_from_candles(candles.iloc[max(0, i - 60) : i + 1]).value
                except Exception:
                    reg = "UNKNOWN"
            regimes.setdefault(reg, []).append(t)

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

    return {
        "trades": n, "win_rate": wr, "wins": wins, "losses": n - wins,
        "profit_factor": pf, "expectancy": expectancy, "total_pnl": pnl, "max_drawdown": dd,
        "avg_win": avg_win, "avg_loss": avg_loss,
        "call_wr": subset(calls)[0], "call_n": subset(calls)[1],
        "put_wr": subset(puts)[0], "put_n": subset(puts)[1],
        "morning_wr": subset(morning)[0], "morning_n": subset(morning)[1],
        "regimes": {k: {"wr": subset(v)[0], "n": subset(v)[1], "pnl": round(sum(float(x.get("pnl") or 0) for x in v), 2)} for k, v in regimes.items()},
        "max_consec_wins": mw, "max_consec_losses": ml,
    }


def score(m, ref_trades):
    """WR-primary; reward more trades + expectancy when WR stays strong."""
    tr = m["trades"]
    if tr < MIN_TRADES:
        return -100.0 + tr + float(m["win_rate"]) * 0.1
    wr = float(m["win_rate"])
    pf = min(float(m["profit_factor"] or 0), 4.0)
    exp = float(m["expectancy"] or 0)
    pnl = float(m["total_pnl"] or 0)
    dd = float(m["max_drawdown"] or 0)
    trade_bonus = min(tr / max(ref_trades, 1), 3.0) * 15.0
    return wr * 2.0 + pf * 12.0 + max(min(exp / 50.0, 25.0), -15.0) + trade_bonus + max(min(pnl / 200.0, 20.0), -10.0) - min(dd / 500.0, 30.0)


def split_wf(candles):
    n = len(candles)
    return candles.iloc[: int(n * 0.6)].reset_index(drop=True), candles.iloc[int(n * 0.6) : int(n * 0.8)].reset_index(drop=True), candles.iloc[int(n * 0.8) :].reset_index(drop=True)


def main() -> int:
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

    install_patches()
    lot = int(INSTRUMENTS[INSTRUMENT_KEY]["lot_size"])
    capital = float(os.environ.get("BACKTEST_CAPITAL", "100000"))
    user_id = int(os.environ.get("BACKTEST_USER_ID", "1"))

    print(f"=== Optimize {STRATEGY_CODE} (lean) · {BACKTEST_DAYS}d ===", flush=True)
    candles, source, from_date, to_date = get_candles(user_id)
    train, val, oos = split_wf(candles)
    print(f"bars={len(candles):,} {from_date}→{to_date} WF {len(train)}/{len(val)}/{len(oos)}", flush=True)

    base = baseline_params()
    rows = []

    def evaluate(label, group, params, dataset="train"):
        data = {"train": train, "val": val, "oos": oos, "full": candles}[dataset]
        m = metrics(run_bt(data, lot, capital, params), data if dataset != "full" else candles)
        sc = score(m, max(base_train["trades"], 7))
        row = {"label": label, "group": group, "dataset": dataset, "params": deepcopy(params), "metrics": m, "score": round(sc, 2)}
        rows.append(row)
        print(f"{group:12} {label:26} [{dataset}] tr={m['trades']:>3} WR={m['win_rate']:>5}% PF={m['profit_factor']:>6} EXP={m['expectancy']:>8} PnL={m['total_pnl']:>9} DD={m['max_drawdown']:>8} sc={sc:>6.1f}", flush=True)
        return row

    def best(group):
        g = [r for r in rows if r["group"] == group and r["dataset"] == "train" and r["metrics"]["trades"] >= MIN_TRADES]
        if not g:
            g = [r for r in rows if r["group"] == group and r["dataset"] == "train" and r["metrics"]["trades"] >= 3]
        return max(g, key=lambda r: r["score"]) if g else None

    print("\n--- BASELINE ---", flush=True)
    base_full = metrics(run_bt(candles, lot, capital, base), candles)
    base_train = metrics(run_bt(train, lot, capital, base), train)
    base_val = metrics(run_bt(val, lot, capital, base), val)
    base_oos = metrics(run_bt(oos, lot, capital, base), oos)
    print(json.dumps({"full": base_full, "train": base_train, "val": base_val, "oos": base_oos}, indent=2), flush=True)

    work = deepcopy(base)

    # 1 OR — lean grid
    print("\n--- 1 OR range ---", flush=True)
    for rmin, rmax in [(80, 200), (90, 200), (100, 200), (100, 220), (110, 220), (120, 220), (120, 240), (90, 240), (100, 260), (70, 220)]:
        p = deepcopy(work)
        p.update({"smc_orb_range_min": float(rmin), "smc_orb_range_max": float(rmax), "smc_orb_skip_wide_or": True})
        evaluate(f"or_{rmin}_{rmax}", "or_range", p)
    if best("or_range"):
        work["smc_orb_range_min"] = best("or_range")["params"]["smc_orb_range_min"]
        work["smc_orb_range_max"] = best("or_range")["params"]["smc_orb_range_max"]

    # 3 pad
    print("\n--- 3 OR pad ---", flush=True)
    for pad in [0.0, 0.0005, 0.0008, 0.0012, 0.0015, 0.002]:
        p = deepcopy(work); p["smc_orb_pad_pct"] = pad; evaluate(f"pad_{pad}", "pad", p)
    if best("pad"):
        work["smc_orb_pad_pct"] = best("pad")["params"]["smc_orb_pad_pct"]

    # 4 buffer
    print("\n--- 4 Buffer ---", flush=True)
    for b in [0.0, 0.05, 0.08, 0.10, 0.12, 0.15, 0.20]:
        p = deepcopy(work); p["entry_buffer_pct"] = b; evaluate(f"buf_{b}", "buffer", p)
    if best("buffer"):
        work["entry_buffer_pct"] = best("buffer")["params"]["entry_buffer_pct"]

    # 5 timing
    print("\n--- 5 Timing ---", flush=True)
    for start in [9 * 60 + 25, 9 * 60 + 30, 9 * 60 + 35, 9 * 60 + 40]:
        p = deepcopy(work); p["smc_orb_entry_start_min"] = start; evaluate(f"start_{start}", "start", p)
    for cut in [10 * 60 + 15, 10 * 60 + 30, 10 * 60 + 45, 11 * 60]:
        p = deepcopy(work); p["smc_orb_entry_cutoff_min"] = cut; evaluate(f"cut_{cut}", "cutoff", p)
    if best("start"):
        work["smc_orb_entry_start_min"] = best("start")["params"]["smc_orb_entry_start_min"]
    if best("cutoff"):
        work["smc_orb_entry_cutoff_min"] = best("cutoff")["params"]["smc_orb_entry_cutoff_min"]

    # 6-7 FVG
    print("\n--- 6-7 FVG ---", flush=True)
    for mode in ["or", "fvg", "momentum", "fvg_preferred"]:
        p = deepcopy(work); p["smc_orb_fvg_mode"] = mode; p["smc_orb_require_fvg"] = mode == "fvg"; evaluate(f"fvg_{mode}", "fvg_mode", p)
    if best("fvg_mode"):
        work["smc_orb_fvg_mode"] = best("fvg_mode")["params"]["smc_orb_fvg_mode"]
        work["smc_orb_require_fvg"] = work["smc_orb_fvg_mode"] == "fvg"
    for g in [0.003, 0.005, 0.007, 0.010, 0.015, 0.020]:
        p = deepcopy(work); p["fvg_min_gap_pct"] = g; evaluate(f"gap_{g}", "fvg_gap", p)
    if best("fvg_gap"):
        work["fvg_min_gap_pct"] = best("fvg_gap")["params"]["fvg_min_gap_pct"]

    # 9 RSI
    print("\n--- 9 RSI ---", flush=True)
    for lo, hi in [(48, 64), (50, 66), (52, 66), (52, 68), (54, 70), (55, 70)]:
        p = deepcopy(work); p["smc_orb_rsi_call_min"] = lo; p["smc_orb_rsi_call_max"] = hi; evaluate(f"call_{lo}_{hi}", "call_rsi", p)
    for lo, hi in [(32, 48), (34, 50), (36, 50), (36, 52), (38, 52), (40, 54)]:
        p = deepcopy(work); p["smc_orb_rsi_put_min"] = lo; p["smc_orb_rsi_put_max"] = hi; evaluate(f"put_{lo}_{hi}", "put_rsi", p)
    if best("call_rsi"):
        work["smc_orb_rsi_call_min"] = best("call_rsi")["params"]["smc_orb_rsi_call_min"]
        work["smc_orb_rsi_call_max"] = best("call_rsi")["params"]["smc_orb_rsi_call_max"]
    if best("put_rsi"):
        work["smc_orb_rsi_put_min"] = best("put_rsi")["params"]["smc_orb_rsi_put_min"]
        work["smc_orb_rsi_put_max"] = best("put_rsi")["params"]["smc_orb_rsi_put_max"]

    # 10-12 mom / reject / slope
    print("\n--- 10-12 Mom/Reject/Slope ---", flush=True)
    for on in [False, True]:
        p = deepcopy(work); p["smc_orb_rsi_slope"] = on; evaluate(f"slope_{on}", "rsi_slope", p)
    for mode in ["two_bar", "one_bar", "two_close", "off"]:
        p = deepcopy(work); p["smc_orb_momentum_mode"] = mode; p["smc_orb_require_momentum"] = mode != "off"; evaluate(f"mom_{mode}", "momentum", p)
    for am in [0.10, 0.15, 0.20]:
        p = deepcopy(work); p["smc_orb_momentum_mode"] = "atr"; p["smc_orb_mom_atr_mult"] = am; p["smc_orb_require_momentum"] = True; evaluate(f"mom_atr_{am}", "momentum", p)
    for b in [0.0, 0.40, 0.50, 0.60]:
        p = deepcopy(work); p["smc_orb_reject_body_min"] = b; evaluate(f"rej_{b}", "reject", p)
    for g in ["rsi_slope", "momentum", "reject"]:
        if best(g):
            for k, v in best(g)["params"].items():
                if k.startswith("smc_orb_"):
                    work[k] = v

    # 13-16 ema / bias / vol
    print("\n--- 13-16 EMA/Bias/Vol ---", flush=True)
    for strict, sep in [(False, 0.0), (True, 0.0), (False, 0.04), (True, 0.04)]:
        p = deepcopy(work); p["smc_orb_ema_strict"] = strict; p["smc_orb_ema_sep_pct"] = sep; evaluate(f"ema_{strict}_{sep}", "ema", p)
    for mode in ["current", "strong15", "align"]:
        p = deepcopy(work); p["smc_orb_bias_mode"] = mode; evaluate(f"bias_{mode}", "bias", p)
    for req in [False, True]:
        p = deepcopy(work); p["smc_orb_require_structure"] = req; evaluate(f"struct_{req}", "structure", p)
    for v in [0.0, 1.10, 1.20, 1.30, 1.40]:
        p = deepcopy(work); p["volume_min"] = v; evaluate(f"vol_{v}", "volume", p)
    for g in ["ema", "bias", "structure", "volume"]:
        if best(g):
            bp = best(g)["params"]
            for k in ("smc_orb_ema_strict", "smc_orb_ema_sep_pct", "smc_orb_bias_mode", "smc_orb_require_structure", "volume_min"):
                if k in bp:
                    work[k] = bp[k]

    # 17-21 risk
    print("\n--- 17-21 Risk/Hold/Trail ---", flush=True)
    for s in [40, 45, 50, 55, 60, 70]:
        p = deepcopy(work); p["smc_orb_stop_pts"] = float(s); evaluate(f"sl_{s}", "stop", p)
    for t in [90, 100, 110, 120, 130, 140, 150]:
        p = deepcopy(work); p["smc_orb_target_pts"] = float(t); evaluate(f"tgt_{t}", "target", p)
    if best("stop"):
        work["smc_orb_stop_pts"] = best("stop")["params"]["smc_orb_stop_pts"]
    if best("target"):
        work["smc_orb_target_pts"] = best("target")["params"]["smc_orb_target_pts"]
    sl_c = sorted([r for r in rows if r["group"] == "stop" and r["metrics"]["trades"] >= 3], key=lambda r: r["score"], reverse=True)[:3]
    tg_c = sorted([r for r in rows if r["group"] == "target" and r["metrics"]["trades"] >= 3], key=lambda r: r["score"], reverse=True)[:3]
    for a, b in product(sl_c, tg_c):
        p = deepcopy(work)
        p["smc_orb_stop_pts"] = a["params"]["smc_orb_stop_pts"]
        p["smc_orb_target_pts"] = b["params"]["smc_orb_target_pts"]
        evaluate(f"rr_{p['smc_orb_stop_pts']}_{p['smc_orb_target_pts']}", "rr", p)
    if best("rr"):
        work["smc_orb_stop_pts"] = best("rr")["params"]["smc_orb_stop_pts"]
        work["smc_orb_target_pts"] = best("rr")["params"]["smc_orb_target_pts"]
    for h in [4, 5, 6, 8, 10, 12]:
        p = deepcopy(work); p["max_hold_bars"] = h; evaluate(f"hold_{h}", "hold", p)
    if best("hold"):
        work["max_hold_bars"] = best("hold")["params"]["max_hold_bars"]
    for tr in [0.0, 0.75, 1.0, 1.25]:
        p = deepcopy(work); p["trailing_atr_mult"] = tr; evaluate(f"trail_{tr}", "trail", p)
    if best("trail"):
        work["trailing_atr_mult"] = best("trail")["params"]["trailing_atr_mult"]

    # 22-23 scan
    print("\n--- 22-23 Scan/spacing ---", flush=True)
    for s in [1, 2, 3, 5]:
        p = deepcopy(work); p["smc_entry_scan_every"] = s; evaluate(f"scan_{s}", "scan", p)
    for m in [3, 5, 8, 10, 12]:
        p = deepcopy(work); p["smc_min_bars_between"] = m; evaluate(f"between_{m}", "between", p)
    if best("scan"):
        work["smc_entry_scan_every"] = best("scan")["params"]["smc_entry_scan_every"]
    if best("between"):
        work["smc_min_bars_between"] = best("between")["params"]["smc_min_bars_between"]

    picks = {g: best(g) for g in ["or_range", "pad", "buffer", "start", "cutoff", "fvg_mode", "fvg_gap", "call_rsi", "put_rsi", "rsi_slope", "momentum", "reject", "ema", "bias", "structure", "volume", "rr", "hold", "trail", "scan", "between"]}
    print("\n--- Best OFAT ---", flush=True)
    for g, r in picks.items():
        if r:
            print(f"  {g}: {r['label']} sc={r['score']} WR={r['metrics']['win_rate']} tr={r['metrics']['trades']}", flush=True)

    # Combos + stability
    print("\n--- Combos ---", flush=True)
    combos = [deepcopy(base), deepcopy(work)]
    for d_sl, d_tg in product([-5, 0, 5], [-10, 0, 10]):
        p = deepcopy(work)
        p["smc_orb_stop_pts"] = max(35, float(p["smc_orb_stop_pts"]) + d_sl)
        p["smc_orb_target_pts"] = max(80, float(p["smc_orb_target_pts"]) + d_tg)
        combos.append(p)
    for dmin in [-10, 0, 10]:
        p = deepcopy(work)
        p["smc_orb_range_min"] = max(70, float(p["smc_orb_range_min"]) + dmin)
        combos.append(p)

    seen = set()
    unique = []
    for p in combos:
        key = json.dumps({k: p.get(k) for k in sorted(p) if str(k).startswith(("smc_", "orb", "fvg", "entry", "volume", "max_hold", "trailing"))}, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    combo_train = [evaluate(f"combo_{i}", "combo", p) for i, p in enumerate(unique)]
    top = sorted([r for r in combo_train if r["metrics"]["trades"] >= MIN_TRADES and r["metrics"]["expectancy"] > 0], key=lambda r: r["score"], reverse=True)[:6]
    if not top:
        top = sorted(combo_train, key=lambda r: r["score"], reverse=True)[:5]

    print("\n--- Validation ---", flush=True)
    val_rows = []
    for tr in top:
        vr = evaluate(tr["label"] + "_val", "combo_val", tr["params"], dataset="val")
        val_rows.append({**vr, "train_score": tr["score"]})

    recommended = sorted(
        val_rows,
        key=lambda r: (1 if r["metrics"]["expectancy"] > 0 else 0, 1 if r["metrics"]["win_rate"] >= 60 else 0, r["score"], r.get("train_score", 0)),
        reverse=True,
    )[0] if val_rows else None

    rec_oos = rec_full = None
    if recommended:
        print("\n--- OOS + Full ---", flush=True)
        rec_oos = evaluate("recommended_oos", "oos", recommended["params"], dataset="oos")
        rec_full = evaluate("recommended_full", "full", recommended["params"], dataset="full")

    eligible = [r for r in rows if r["dataset"] == "train" and r["metrics"]["trades"] >= MIN_TRADES]
    ranked = sorted(eligible, key=lambda r: r["score"], reverse=True)

    report = {
        "strategy": STRATEGY_CODE,
        "data_source": source,
        "date_range": {"from": from_date, "to": to_date},
        "bars": len(candles),
        "walk_forward": {"train": len(train), "val": len(val), "oos": len(oos)},
        "baseline": {"params": base, "full": base_full, "train": base_train, "val": base_val, "oos": base_oos},
        "ofat_best": {k: ({"label": v["label"], "score": v["score"], "metrics": v["metrics"], "params": v["params"]} if v else None) for k, v in picks.items()},
        "top10_train": ranked[:10],
        "recommended": recommended,
        "recommended_oos": rec_oos,
        "recommended_full": rec_full,
        "notes": [
            "Baseline already ~100% WR with few trades and small expectancy; score favors WR + trade count + expectancy.",
            "merge_smc_orb_fvg_params fixed so overrides apply.",
            "Patched evaluator for start/FVG-mode/rejection/bias/EMA knobs during OFAT.",
        ],
    }
    out = os.environ.get("REPORT_PATH", "/tmp/optimize_scalp_smc006_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote {out}", flush=True)
    print("\n=== TOP 10 TRAIN ===", flush=True)
    for i, r in enumerate(ranked[:10], 1):
        m = r["metrics"]
        print(f"{i:2}. [{r['group']}] {r['label']} sc={r['score']} WR={m['win_rate']}% PF={m['profit_factor']} tr={m['trades']} PnL={m['total_pnl']} DD={m['max_drawdown']}", flush=True)
    if recommended:
        print("\n=== RECOMMENDED ===", flush=True)
        print(json.dumps({"params": recommended["params"], "val": recommended["metrics"], "oos": (rec_oos or {}).get("metrics"), "full": (rec_full or {}).get("metrics")}, indent=2, default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
