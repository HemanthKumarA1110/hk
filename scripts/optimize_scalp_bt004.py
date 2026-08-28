#!/usr/bin/env python3
"""SCALP-BT-004 OFAT + walk-forward — Nifty 50 ORB.

True baseline is recorded unchanged. Because baseline fires ~1 trade under
stacked filters, OFAT runs one-factor-at-a-time from a session-aligned probe
base (afternoon enabled + prior-bar OFF + vol 1.15) so each knob has enough
sample size. Winners are then combined, stability-tested, and walk-forward
validated (60/20/20). Defaults are NOT modified by this script.
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
MIN_TRADES = int(os.environ.get("MIN_TRADES", "5"))
CANDLE_CACHE = os.environ.get("CANDLE_CACHE", "/tmp/bt004_candles.pkl")
QUICK = os.environ.get("QUICK", "0") == "1"

OR_MINS = [25, 30, 35, 40, 45, 50]
OR_MAXS = [60, 65, 70, 75, 80, 85, 90, 100]
BUFFER_POINTS = [0, 0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6]
PRIOR_MODES = [
    ("A_complete_inside", "inside"),
    ("B_close_inside", "close_inside"),
    ("C_not_beyond", "not_beyond"),
    ("D_off", "off"),
]
CALL_RSI = [(48, 62), (50, 62), (50, 65), (52, 64), (52, 66), (54, 66), (54, 68), (55, 70)]
PUT_RSI = [(30, 46), (32, 46), (34, 46), (34, 48), (36, 48), (36, 50), (38, 50), (38, 52)]
VOL_RATIOS = [1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35, 1.40, 1.50, 1.60]
VOL_LOOKBACKS = [0, 10, 15, 20, 25, 30]
FAST_EMAS = [5, 7, 8, 9, 10, 12]
SLOW_EMAS = [18, 20, 21, 24, 26]
EMA_FOCUS = {(8, 20), (8, 21), (9, 20), (9, 21), (9, 24), (10, 21), (10, 24), (12, 24), (12, 26)}
SEP_PCTS = [0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.07, 0.10]
BODY_PCTS = [0.0, 0.30, 0.40, 0.50, 0.60]
STOPS = [4, 4.5, 5, 5.5, 6, 6.5, 7, 8, 9, 10]
TARGETS = [8, 9, 10, 11, 12, 13, 14, 15, 16, 18, 20]
HOLDS = [3, 4, 5, 6, 7, 8, 10, 12, 15]
MOM_ATR = [0.05, 0.10, 0.15, 0.20, 0.25]

_SESSION_MODE = "both"
_REGIME_ALLOW: set[str] | None = None
_ORIG_EVAL = None


def get_candles():
    with open(CANDLE_CACHE, "rb") as f:
        payload = pickle.load(f)
    return payload["df"], payload["source"], payload["from_date"], payload["to_date"]


def spot_ref(candles) -> float:
    return float(candles["close"].astype(float).median())


def pts_to_pct(pts: float, spot: float) -> float:
    return float(pts) / max(spot, 1.0)


def baseline_params() -> dict[str, Any]:
    from trading_shared.strategies.scalping_desk.orb_breakout_tuning import ORB_BREAKOUT_NIFTY_DEFAULTS

    return dict(ORB_BREAKOUT_NIFTY_DEFAULTS)


def install_patches() -> None:
    global _ORIG_EVAL
    import trading_shared.strategies.scalping_desk.battle_tested_scalp as bts

    if _ORIG_EVAL is None:
        _ORIG_EVAL = bts.evaluate_orb_breakout

    def wrapped(df, timeframe, option_chain, lot_size, **kwargs):
        signal = _ORIG_EVAL(df, timeframe, option_chain, lot_size, **kwargs)
        if signal is None:
            return None
        ts = df.iloc[-1].get("timestamp") if len(df) else None
        ist = bts._to_ist(ts)
        if ist is not None and _SESSION_MODE != "both":
            minutes = ist.hour * 60 + ist.minute
            morning = 9 * 60 + 20 <= minutes <= 10 * 60 + 30
            afternoon = 13 * 60 + 30 <= minutes <= 14 * 60 + 45
            if _SESSION_MODE == "morning" and not morning:
                return None
            if _SESSION_MODE == "afternoon" and not afternoon:
                return None
        if _REGIME_ALLOW is not None:
            try:
                from trading_shared.strategies.scalping_desk.market_context import (
                    detect_regime_from_candles,
                )

                reg = str(detect_regime_from_candles(df.tail(60)).value)
                allow = {x.upper() for x in _REGIME_ALLOW}
                if reg.upper() not in allow:
                    return None
            except Exception:
                pass
        return signal

    bts.evaluate_orb_breakout = wrapped
    bts.BATTLE_REGISTRY["orb_breakout"]["evaluate"] = wrapped


def set_filters(*, session: str = "both", regimes: set[str] | None = None) -> None:
    global _SESSION_MODE, _REGIME_ALLOW
    _SESSION_MODE = session
    _REGIME_ALLOW = regimes


def run_bt(candles, lot: int, capital: float, orb: dict[str, Any]) -> dict[str, Any]:
    from trading_shared.strategies.scalping_desk.backtest import run_strategy_backtest

    return run_strategy_backtest(
        candles,
        "1m",
        lot,
        capital,
        strategy_code=STRATEGY_CODE,
        instrument_key=INSTRUMENT_KEY,
        params={"orb_breakout": orb},
        max_loss_per_day=5000,
        max_trades_per_day=5,
    )


def _parse_hhmm(ts: str) -> int | None:
    if not ts:
        return None
    try:
        part = ts.split("T")[1][:5] if "T" in ts else ts.split(" ")[1][:5]
        hh, mm = part.split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        return None


def consecutive_streaks(trades: list[dict[str, Any]]) -> tuple[int, int]:
    max_w = max_l = cur_w = cur_l = 0
    for t in trades:
        if float(t.get("pnl") or 0) > 0:
            cur_w += 1
            cur_l = 0
            max_w = max(max_w, cur_w)
        else:
            cur_l += 1
            cur_w = 0
            max_l = max(max_l, cur_l)
    return max_w, max_l


def subset_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "wr": None, "pnl": 0.0, "pf": None, "exp": None, "dd": 0.0, "wins": 0, "losses": 0}
    wins = [t for t in rows if float(t.get("pnl") or 0) > 0]
    losses = [t for t in rows if float(t.get("pnl") or 0) <= 0]
    pnl = sum(float(t.get("pnl") or 0) for t in rows)
    gp = sum(float(t.get("pnl") or 0) for t in wins)
    gl = abs(sum(float(t.get("pnl") or 0) for t in losses))
    pf = round(gp / gl, 2) if gl else round(gp, 2)
    eq = peak = dd = 0.0
    for t in rows:
        eq += float(t.get("pnl") or 0)
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "n": len(rows),
        "wr": round(len(wins) / len(rows) * 100, 2),
        "pnl": round(pnl, 2),
        "pf": pf,
        "exp": round(pnl / len(rows), 2),
        "dd": round(dd, 2),
        "wins": len(wins),
        "losses": len(losses),
    }


def metrics(result: dict[str, Any], candles=None) -> dict[str, Any]:
    trades = result.get("trades") or []
    n = int(result.get("total_trades") or 0)
    pnl = float(result.get("total_pnl") or 0)
    calls = [t for t in trades if str(t.get("signal_type")).upper() == "CALL"]
    puts = [t for t in trades if str(t.get("signal_type")).upper() == "PUT"]
    morning, afternoon = [], []
    buckets = {k: [] for k in (
        "09:20-09:30", "09:30-09:45", "09:45-10:00", "10:00-10:15", "10:15-10:30",
        "13:30-14:00", "14:00-14:30", "14:30-14:45",
    )}
    for t in trades:
        hhmm = _parse_hhmm(str(t.get("entry_time") or ""))
        if hhmm is None:
            continue
        if 9 * 60 + 20 <= hhmm <= 10 * 60 + 30:
            morning.append(t)
        elif 13 * 60 + 30 <= hhmm <= 14 * 60 + 45:
            afternoon.append(t)
        if 9 * 60 + 20 <= hhmm < 9 * 60 + 30:
            buckets["09:20-09:30"].append(t)
        elif 9 * 60 + 30 <= hhmm < 9 * 60 + 45:
            buckets["09:30-09:45"].append(t)
        elif 9 * 60 + 45 <= hhmm < 10 * 60:
            buckets["09:45-10:00"].append(t)
        elif 10 * 60 <= hhmm < 10 * 60 + 15:
            buckets["10:00-10:15"].append(t)
        elif 10 * 60 + 15 <= hhmm <= 10 * 60 + 30:
            buckets["10:15-10:30"].append(t)
        elif 13 * 60 + 30 <= hhmm < 14 * 60:
            buckets["13:30-14:00"].append(t)
        elif 14 * 60 <= hhmm < 14 * 60 + 30:
            buckets["14:00-14:30"].append(t)
        elif 14 * 60 + 30 <= hhmm <= 14 * 60 + 45:
            buckets["14:30-14:45"].append(t)

    max_w, max_l = consecutive_streaks(trades)
    wins = [t for t in trades if float(t.get("pnl") or 0) > 0]
    losses = [t for t in trades if float(t.get("pnl") or 0) <= 0]

    regimes: dict[str, list] = {}
    if candles is not None and len(candles) and trades:
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
        "win_rate": float(result.get("win_rate") or 0),
        "profit_factor": float(result.get("profit_factor") or 0),
        "expectancy": round(pnl / n, 2) if n else 0.0,
        "total_pnl": pnl,
        "max_drawdown": float(result.get("max_drawdown") or 0),
        "avg_win": float(result.get("avg_profit_win") or 0),
        "avg_loss": float(result.get("avg_loss_loss") or 0),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "max_consec_wins": max_w,
        "max_consec_losses": max_l,
        "call_n": len(calls),
        "put_n": len(puts),
        "call_wr": wr(calls),
        "put_wr": wr(puts),
        "morning_n": len(morning),
        "afternoon_n": len(afternoon),
        "morning_wr": wr(morning),
        "afternoon_wr": wr(afternoon),
        "session_detail": {
            "morning": subset_stats(morning),
            "afternoon": subset_stats(afternoon),
            "CALL": subset_stats(calls),
            "PUT": subset_stats(puts),
        },
        "time_buckets": {k: subset_stats(v) for k, v in buckets.items()},
        "regimes": {k: subset_stats(v) for k, v in regimes.items()},
    }


def balanced_score(m: dict[str, Any], baseline_trades: int) -> float:
    trades = m["trades"]
    if trades < MIN_TRADES:
        return -100.0 + trades
    wr = float(m["win_rate"] or 0)
    pf = min(float(m["profit_factor"] or 0), 4.0)
    exp = float(m["expectancy"] or 0)
    dd = float(m["max_drawdown"] or 0)
    pnl = float(m["total_pnl"] or 0)
    if exp <= 0:
        return wr * 0.6 + pf * 3.0 - 20.0
    trade_ratio = trades / max(baseline_trades, 8)
    trade_score = max(0.0, min(trade_ratio, 2.0)) * 14.0
    if trade_ratio < 0.45:
        trade_score -= 18.0
    dd_penalty = min(dd / 800.0, 35.0)
    exp_score = max(min(exp / 150.0, 18.0), -18.0)
    pnl_score = max(min(pnl / 4000.0, 14.0), -14.0)
    return wr * 2.2 + pf * 16.0 + exp_score + trade_score + pnl_score - dd_penalty


def split_wf(candles):
    n = len(candles)
    return (
        candles.iloc[: int(n * 0.60)].reset_index(drop=True),
        candles.iloc[int(n * 0.60) : int(n * 0.80)].reset_index(drop=True),
        candles.iloc[int(n * 0.80) :].reset_index(drop=True),
    )


def probe_base(base: dict[str, Any]) -> dict[str, Any]:
    """Session-aligned searchable base when stacked defaults starve trades."""
    p = deepcopy(base)
    p.update(
        {
            "orb_entry_cutoff_min": 14 * 60 + 45,  # allow afternoon battle window
            "orb_prior_mode": "off",
            "orb_require_inside_or": False,
            "orb_vol_min": 1.15,
            "orb_or_range_min": 30.0,
            "orb_or_range_max": 90.0,
            "orb_skip_wide_or": True,
        }
    )
    return p


def main() -> int:
    import trading_shared.strategies.scalping_desk.backtest as bt
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

    bt.MAX_BACKTEST_BARS = int(os.environ.get("MAX_BACKTEST_BARS", "40000"))
    install_patches()
    set_filters()

    capital = float(os.environ.get("BACKTEST_CAPITAL", "100000"))
    lot = int(INSTRUMENTS[INSTRUMENT_KEY]["lot_size"])
    candles, source, from_date, to_date = get_candles()
    spot = spot_ref(candles)
    train, val, oos = split_wf(candles)
    print(
        f"=== {STRATEGY_CODE} bars={len(candles)} {from_date}→{to_date} spot={spot:.1f} "
        f"WF={len(train)}/{len(val)}/{len(oos)} QUICK={QUICK} ===",
        flush=True,
    )

    base = baseline_params()
    print("\n--- TRUE BASELINE (unchanged defaults, full sample) ---", flush=True)
    base_full = metrics(run_bt(candles, lot, capital, base), candles)
    print(json.dumps({k: base_full[k] for k in (
        "trades", "win_rate", "profit_factor", "expectancy", "total_pnl", "max_drawdown",
        "winning_trades", "losing_trades", "avg_win", "avg_loss",
        "max_consec_wins", "max_consec_losses",
        "call_n", "call_wr", "put_n", "put_wr",
        "morning_n", "morning_wr", "afternoon_n", "afternoon_wr",
    )}, indent=2), flush=True)

    probe = probe_base(base)
    print("\n--- PROBE BASE (OFAT reference; afternoon + prior OFF + vol 1.15 + OR 30-90) ---", flush=True)
    probe_m = metrics(run_bt(train, lot, capital, probe), train)
    print(json.dumps({k: probe_m[k] for k in ("trades", "win_rate", "profit_factor", "expectancy", "total_pnl", "max_drawdown")}, indent=2), flush=True)
    if probe_m["trades"] < MIN_TRADES:
        print("Probe still too thin — abort", flush=True)
        return 1

    rows: list[dict[str, Any]] = []
    ref_trades = max(probe_m["trades"], 8)

    def evaluate(label: str, group: str, orb: dict[str, Any], data=None, dataset="train") -> dict[str, Any]:
        frame = data if data is not None else train
        m = metrics(run_bt(frame, lot, capital, orb), frame)
        sc = balanced_score(m, ref_trades)
        row = {
            "label": label,
            "group": group,
            "dataset": dataset,
            "params": {k: orb[k] for k in sorted(orb) if str(k).startswith("orb_")},
            "metrics": m,
            "score": round(sc, 2),
        }
        rows.append(row)
        print(
            f"{group:12} {label:30} n={m['trades']:>3} WR={m['win_rate']:>6}% "
            f"PF={m['profit_factor']:>5} EXP={m['expectancy']:>8} "
            f"PnL={m['total_pnl']:>9} DD={m['max_drawdown']:>8} sc={sc:>6.1f}",
            flush=True,
        )
        return row

    def best(group: str) -> dict[str, Any] | None:
        g = [r for r in rows if r["group"] == group and r["dataset"] == "train" and r["metrics"]["trades"] >= MIN_TRADES]
        if not g:
            return None
        # Prefer WR then score, with trade floor
        return max(g, key=lambda r: (r["score"], r["metrics"]["win_rate"], r["metrics"]["trades"]))

    # Classic OFAT: mutate one factor from probe
    print("\n--- 1 OR range ---", flush=True)
    pairs = list(product(OR_MINS, OR_MAXS))
    if QUICK:
        pairs = [(a, b) for a, b in pairs if b - a >= 25 and a in (25, 30, 35, 40, 45) and b in (70, 80, 90, 100)]
    for rmin, rmax in pairs:
        if rmin >= rmax:
            continue
        orb = deepcopy(probe)
        orb.update({"orb_or_range_min": float(rmin), "orb_or_range_max": float(rmax)})
        evaluate(f"or_{rmin}_{rmax}", "or_range", orb)

    print("\n--- 2 Buffer ---", flush=True)
    for pts in BUFFER_POINTS:
        orb = deepcopy(probe)
        orb["orb_buffer_pct"] = pts_to_pct(pts, spot)
        evaluate(f"buf_{pts}", "buffer", orb)

    print("\n--- 3 Prior bar ---", flush=True)
    for name, mode in PRIOR_MODES:
        orb = deepcopy(probe)
        orb["orb_prior_mode"] = mode
        orb["orb_require_inside_or"] = mode in ("inside", "close_inside")
        evaluate(name, "prior", orb)

    print("\n--- 4 CALL RSI ---", flush=True)
    for lo, hi in CALL_RSI:
        orb = deepcopy(probe)
        orb.update({"orb_rsi_call_min": lo, "orb_rsi_call_max": hi})
        evaluate(f"call_{lo}_{hi}", "call_rsi", orb)

    print("\n--- 5 PUT RSI ---", flush=True)
    for lo, hi in PUT_RSI:
        orb = deepcopy(probe)
        orb.update({"orb_rsi_put_min": lo, "orb_rsi_put_max": hi})
        evaluate(f"put_{lo}_{hi}", "put_rsi", orb)

    print("\n--- 6 Volume ---", flush=True)
    for v in VOL_RATIOS:
        orb = deepcopy(probe)
        orb["orb_vol_min"] = float(v)
        evaluate(f"vol_{v:.2f}", "volume", orb)

    print("\n--- 6b Vol lookback ---", flush=True)
    for lb in VOL_LOOKBACKS:
        orb = deepcopy(probe)
        orb["orb_vol_lookback"] = int(lb)
        evaluate(f"vollb_{lb}", "vol_lb", orb)

    print("\n--- 7 EMA ---", flush=True)
    ema_pairs = [(f, s) for f, s in product(FAST_EMAS, SLOW_EMAS) if f < s]
    if QUICK:
        ema_pairs = [p for p in ema_pairs if p in EMA_FOCUS or p == (9, 21)]
    for f, s in ema_pairs:
        orb = deepcopy(probe)
        orb.update({"orb_ema_fast": int(f), "orb_ema_slow": int(s)})
        evaluate(f"ema_{f}_{s}", "ema", orb)

    print("\n--- 8 EMA sep ---", flush=True)
    for sep in SEP_PCTS:
        orb = deepcopy(probe)
        orb["orb_min_separation_pct"] = float(sep)
        evaluate(f"sep_{sep}", "ema_sep", orb)

    print("\n--- 9 Momentum ---", flush=True)
    for flag, mode in ((True, "two_bar"), (False, "two_bar"), (True, "directional")):
        orb = deepcopy(probe)
        orb.update({"orb_require_two_bar_momentum": flag, "orb_momentum_mode": mode})
        evaluate(f"mom_{mode}_{flag}", "momentum", orb)
    for atr_m in MOM_ATR:
        orb = deepcopy(probe)
        orb.update({"orb_require_two_bar_momentum": True, "orb_momentum_mode": "atr", "orb_momentum_atr_mult": float(atr_m)})
        evaluate(f"mom_atr_{atr_m}", "momentum", orb)

    print("\n--- 9b RSI slope ---", flush=True)
    for flag in (False, True):
        orb = deepcopy(probe)
        orb["orb_require_rsi_slope"] = flag
        evaluate(f"slope_{flag}", "rsi_slope", orb)

    print("\n--- 10 Candle body ---", flush=True)
    for b in BODY_PCTS:
        orb = deepcopy(probe)
        orb["orb_min_body_pct"] = float(b)
        evaluate(f"body_{b}", "candle", orb)

    print("\n--- 11 Stop ---", flush=True)
    for sl in STOPS:
        orb = deepcopy(probe)
        orb["orb_stop_pts"] = float(sl)
        evaluate(f"sl_{sl}", "stop", orb)

    print("\n--- 12 Target ---", flush=True)
    for tp in TARGETS:
        orb = deepcopy(probe)
        orb["orb_target_pts"] = float(tp)
        evaluate(f"tp_{tp}", "target", orb)

    # Compose work from OFAT winners
    picks = {g: best(g) for g in (
        "or_range", "buffer", "prior", "call_rsi", "put_rsi", "volume", "vol_lb",
        "ema", "ema_sep", "momentum", "rsi_slope", "candle", "stop", "target",
    )}
    print("\n--- OFAT winners ---", flush=True)
    work = deepcopy(probe)
    for g, row in picks.items():
        if not row:
            print(f"  {g}: none", flush=True)
            continue
        print(f"  {g}: {row['label']} sc={row['score']} WR={row['metrics']['win_rate']} n={row['metrics']['trades']}", flush=True)
        for k, v in row["params"].items():
            # Only apply keys that this group owns
            owners = {
                "or_range": ("orb_or_range_min", "orb_or_range_max", "orb_skip_wide_or"),
                "buffer": ("orb_buffer_pct",),
                "prior": ("orb_prior_mode", "orb_require_inside_or"),
                "call_rsi": ("orb_rsi_call_min", "orb_rsi_call_max"),
                "put_rsi": ("orb_rsi_put_min", "orb_rsi_put_max"),
                "volume": ("orb_vol_min", "orb_use_vol_spike"),
                "vol_lb": ("orb_vol_lookback",),
                "ema": ("orb_ema_fast", "orb_ema_slow"),
                "ema_sep": ("orb_min_separation_pct",),
                "momentum": ("orb_require_two_bar_momentum", "orb_momentum_mode", "orb_momentum_atr_mult"),
                "rsi_slope": ("orb_require_rsi_slope",),
                "candle": ("orb_min_body_pct",),
                "stop": ("orb_stop_pts",),
                "target": ("orb_target_pts",),
            }
            if k in owners.get(g, ()):
                work[k] = v

    print("\n--- 13 SL/TP combo ---", flush=True)
    sl_c = sorted({float(work["orb_stop_pts"]), 5.0, 5.5, 6.0, 6.5, 7.0})
    tp_c = sorted({float(work["orb_target_pts"]), 10.0, 11.0, 12.0, 13.0, 14.0, 15.0})
    if QUICK:
        sl_c = sorted({float(work["orb_stop_pts"]), 5.5, 6.0, 7.0})
        tp_c = sorted({float(work["orb_target_pts"]), 10.0, 12.0, 14.0})
    for sl, tp in product(sl_c, tp_c):
        if tp <= sl:
            continue
        orb = deepcopy(work)
        orb.update({"orb_stop_pts": float(sl), "orb_target_pts": float(tp)})
        evaluate(f"rr_{sl}_{tp}", "sl_tp", orb)
    best_rr = best("sl_tp")
    if best_rr:
        work["orb_stop_pts"] = float(best_rr["params"]["orb_stop_pts"])
        work["orb_target_pts"] = float(best_rr["params"]["orb_target_pts"])

    print("\n--- 14 Max hold ---", flush=True)
    for h in HOLDS:
        orb = deepcopy(work)
        orb["orb_max_hold_bars"] = int(h)
        evaluate(f"hold_{h}", "hold", orb)
    best_h = best("hold")
    if best_h:
        work["orb_max_hold_bars"] = int(best_h["params"]["orb_max_hold_bars"])

    print("\n--- 15 VWAP ---", flush=True)
    for flag in (False, True):
        orb = deepcopy(work)
        orb["orb_require_vwap"] = flag
        evaluate(f"vwap_{flag}", "vwap", orb)
    best_v = best("vwap")
    if best_v:
        work["orb_require_vwap"] = bool(best_v["params"]["orb_require_vwap"])

    print("\n--- 16 Session ---", flush=True)
    for cut in (10 * 60 + 30, 14 * 60 + 45):
        orb = deepcopy(work)
        orb["orb_entry_cutoff_min"] = cut
        evaluate(f"cut_{cut}", "cutoff", orb)
    for sess in ("both", "morning", "afternoon"):
        set_filters(session=sess)
        orb = deepcopy(work)
        orb["orb_entry_cutoff_min"] = 14 * 60 + 45 if sess != "morning" else 10 * 60 + 30
        evaluate(f"sess_{sess}", "session", orb)
    set_filters()
    best_cut = best("cutoff")
    if best_cut:
        work["orb_entry_cutoff_min"] = int(best_cut["params"]["orb_entry_cutoff_min"])

    print("\n--- 17 Regime ---", flush=True)
    for name, regs in (
        ("all", None),
        ("trend_hv", {"TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"}),
        ("trend", {"TRENDING_UP", "TRENDING_DOWN"}),
        ("hv", {"HIGH_VOLATILITY"}),
    ):
        set_filters(regimes=regs)
        evaluate(f"reg_{name}", "regime", deepcopy(work))
    set_filters()

    # Compact refined combos around winners
    print("\n--- Refined combos ---", flush=True)
    combo_seeds = [deepcopy(work), deepcopy(probe)]
    # re-tighten prior if it scored well alone
    if picks.get("prior"):
        c = deepcopy(work)
        c["orb_prior_mode"] = picks["prior"]["params"]["orb_prior_mode"]
        c["orb_require_inside_or"] = bool(picks["prior"]["params"].get("orb_require_inside_or", False))
        combo_seeds.append(c)
    # morning-only variant
    c = deepcopy(work)
    c["orb_entry_cutoff_min"] = 10 * 60 + 30
    combo_seeds.append(c)
    # restore close_inside prior (strategy concept) on top of other wins
    c = deepcopy(work)
    c.update({"orb_prior_mode": "close_inside", "orb_require_inside_or": True, "orb_vol_min": min(float(work["orb_vol_min"]), 1.20)})
    combo_seeds.append(c)
    # WR-focused: higher vol + body
    c = deepcopy(work)
    c.update({"orb_vol_min": max(float(work["orb_vol_min"]), 1.25), "orb_min_body_pct": max(float(work.get("orb_min_body_pct") or 0), 0.4)})
    combo_seeds.append(c)

    seen = set()
    for i, orb in enumerate(combo_seeds):
        key = json.dumps(orb, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        evaluate(f"combo_{i}", "combo", orb)

    # Stability
    print("\n--- Stability ---", flush=True)
    buf_pts = float(work["orb_buffer_pct"]) * spot
    for pts in sorted({max(0, buf_pts + d) for d in (-1, -0.5, 0, 0.5, 1)}):
        orb = deepcopy(work)
        orb["orb_buffer_pct"] = pts_to_pct(pts, spot)
        evaluate(f"stab_buf_{pts:.1f}", "stability", orb)
    for sl in sorted({float(work["orb_stop_pts"]) + d for d in (-0.5, 0, 0.5)}):
        if sl < 3:
            continue
        orb = deepcopy(work)
        orb["orb_stop_pts"] = float(sl)
        evaluate(f"stab_sl_{sl}", "stability", orb)

    # Rank combos + ofat on train
    eligible = [
        r for r in rows
        if r["dataset"] == "train"
        and r["group"] in ("combo", "sl_tp", "hold", "vwap", "or_range", "volume", "ema", "prior", "buffer")
        and r["metrics"]["trades"] >= MIN_TRADES
        and r["metrics"]["expectancy"] > 0
    ]
    ranked = sorted(eligible, key=lambda r: (r["score"], r["metrics"]["win_rate"], r["metrics"]["trades"]), reverse=True)
    if not ranked:
        ranked = sorted(
            [r for r in rows if r["dataset"] == "train" and r["metrics"]["trades"] >= MIN_TRADES],
            key=lambda r: r["score"],
            reverse=True,
        )
    top = ranked[0] if ranked else None
    rec_params = deepcopy(top["params"]) if top else deepcopy(work)

    print("\n--- Walk-forward ---", flush=True)
    for label, frame, ds in (
        ("rec_train", train, "train"),
        ("rec_val", val, "val"),
        ("rec_oos", oos, "oos"),
        ("rec_full", candles, "full"),
        ("base_full", candles, "full"),
    ):
        params = base if label == "base_full" else rec_params
        evaluate(label, "final", params, data=frame, dataset=ds)

    rec_train = next(r for r in rows if r["label"] == "rec_train")
    rec_val = next(r for r in rows if r["label"] == "rec_val")
    rec_oos = next(r for r in rows if r["label"] == "rec_oos")
    rec_full = next(r for r in rows if r["label"] == "rec_full")
    base_row = next(r for r in rows if r["label"] == "base_full")

    # Losing trade autopsy on recommended full
    losses = [t for t in (run_bt(candles, lot, capital, rec_params).get("trades") or []) if float(t.get("pnl") or 0) <= 0]
    autopsy = {
        "losing_n": len(losses),
        "by_exit": {},
        "by_side": subset_stats(losses),
        "sample": losses[:8],
    }
    for t in losses:
        reason = str(t.get("exit_reason") or "?")
        autopsy["by_exit"][reason] = autopsy["by_exit"].get(reason, 0) + 1

    report = {
        "strategy": STRATEGY_CODE,
        "instrument": INSTRUMENT_KEY,
        "source": source,
        "date_range": {"from": from_date, "to": to_date},
        "bars": len(candles),
        "spot_ref": spot,
        "notes": [
            "True baseline uses unchanged ORB_BREAKOUT_NIFTY_DEFAULTS.",
            "Baseline trade count is extremely low (~1) due to stacked filters + morning-only cutoff.",
            "OFAT uses probe base: afternoon cutoff + prior OFF + vol 1.15 + OR 30-90.",
            "Recommended params validated on 60/20/20 walk-forward; OOS not used for tuning.",
        ],
        "baseline_full": {"params": base, "metrics": base_full},
        "probe": {"params": probe, "metrics": probe_m},
        "ofat_picks": {k: (v["label"] if v else None) for k, v in picks.items()},
        "recommended": {
            "source": top["label"] if top else "work",
            "params": rec_params,
            "train": rec_train["metrics"],
            "val": rec_val["metrics"],
            "oos": rec_oos["metrics"],
            "full": rec_full["metrics"],
        },
        "baseline_vs_opt": {"baseline": base_row["metrics"], "optimized": rec_full["metrics"]},
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
            for i, r in enumerate(ranked[:10], 1)
        ],
        "loss_autopsy": autopsy,
    }

    out = os.environ.get("REPORT_PATH", "/tmp/optimize_scalp_bt004_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote {out}", flush=True)
    print("\n=== TOP 10 ===", flush=True)
    for r in report["top10"]:
        print(
            f"{r['rank']:2}. [{r['group']}] {r['label']} WR={r['win_rate']}% PF={r['profit_factor']} "
            f"EXP={r['expectancy']} n={r['trades']} PnL={r['total_pnl']} DD={r['max_drawdown']} sc={r['score']}",
            flush=True,
        )
    print("\n=== RECOMMENDED ===", flush=True)
    print(json.dumps(rec_params, indent=2, default=str), flush=True)
    print("\n=== WF ===", flush=True)
    slim = lambda m: {k: m.get(k) for k in ("trades", "win_rate", "profit_factor", "expectancy", "total_pnl", "max_drawdown", "call_wr", "put_wr", "morning_wr", "afternoon_wr")}
    print(json.dumps({
        "train": slim(rec_train["metrics"]),
        "val": slim(rec_val["metrics"]),
        "oos": slim(rec_oos["metrics"]),
        "full_opt": slim(rec_full["metrics"]),
        "full_base": slim(base_row["metrics"]),
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
