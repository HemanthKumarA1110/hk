#!/usr/bin/env python3
"""Lean OFAT + walk-forward for INTRA-ORB (equity cash ORB).

Uses DB 5m Nifty50-EQ candles. Caches frames to /tmp/intra_orb_frames.pkl.

    PYTHONUNBUFFERED=1 python /app/scripts/optimize_intra_orb.py
"""

from __future__ import annotations

import json
import os
import pickle
import sys
import time
from copy import deepcopy
from datetime import date, timedelta
from typing import Any

STRATEGY_CODE = "INTRA-ORB"
MIN_TRADES = int(os.environ.get("MIN_TRADES", "5"))
TOP_N = int(os.environ.get("BACKTEST_TOP_N", "0"))  # 0 = all symbols
CAPITAL = float(os.environ.get("BACKTEST_CAPITAL", "100000"))
CACHE = os.environ.get("CANDLE_CACHE", "/tmp/intra_orb_frames.pkl")
QUICK = os.environ.get("QUICK", "0") == "1"


def baseline_params() -> dict[str, Any]:
    from trading_shared.strategies.intraday_desk.intra_orb_tuning import INTRA_ORB_LEGACY

    return dict(INTRA_ORB_LEGACY)


def load_frames():
    if os.path.isfile(CACHE) and os.environ.get("FORCE_RELOAD") != "1":
        with open(CACHE, "rb") as f:
            payload = pickle.load(f)
        print(f"Loaded cache {CACHE}: symbols={len(payload['frames'])}", flush=True)
        return payload

    from trading_shared.backtest.data_loader import BacktestDataLoader
    from trading_shared.db.session import SessionLocal
    from trading_shared.strategies.intraday_desk.stock_picker import default_universe

    user_id = int(os.environ.get("BACKTEST_USER_ID", "1"))
    days = int(os.environ.get("BACKTEST_DAYS", "60"))
    to_date = date.today()
    from_date = to_date - timedelta(days=days)
    db = SessionLocal()
    frames = []
    source = "database"
    try:
        loader = BacktestDataLoader(db)
        for symbol in default_universe():
            try:
                token, resolved = loader.resolve_token(symbol, None)
                df, src = loader.load(
                    user_id=user_id,
                    symbol=resolved,
                    token=token,
                    exchange="NSE",
                    interval="5m",
                    from_date=from_date.isoformat(),
                    to_date=to_date.isoformat(),
                    use_demo_data=False,
                )
                if len(df) >= 30:
                    frames.append((resolved, df))
                    source = src
                    print(f"  {resolved}: {len(df)} bars ({src})", flush=True)
            except Exception as exc:
                print(f"  skip {symbol}: {exc}", flush=True)
    finally:
        db.close()
    payload = {
        "frames": frames,
        "source": source,
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
    }
    with open(CACHE, "wb") as f:
        pickle.dump(payload, f)
    print(f"Cached {len(frames)} symbols → {CACHE}", flush=True)
    return payload


def split_frames(frames, start_frac=0.0, end_frac=1.0):
    out = []
    for sym, df in frames:
        n = len(df)
        a = int(n * start_frac)
        b = int(n * end_frac)
        part = df.iloc[a:b].reset_index(drop=True)
        if len(part) >= 30:
            out.append((sym, part))
    return out


def run_universe(frames, params, picks=None, capital=CAPITAL):
    from trading_shared.strategies.intraday_desk.backtest import run_intraday_universe_backtest

    if picks is None:
        picks = [{"symbol": sym, "score": 1.0} for sym, _ in frames]
        if TOP_N > 0:
            picks = picks[:TOP_N]
    return run_intraday_universe_backtest(
        loader=None,
        user_id=1,
        strategy_code=STRATEGY_CODE,
        exchange="NSE",
        interval="5m",
        from_date="",
        to_date="",
        use_demo_data=False,
        initial_capital=capital,
        risk_pct=1.0,
        top_n=max(len(picks), 1),
        params=params,
        symbol_frames=frames,
        picks=picks,
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


def metrics(res):
    trades = res.get("trades") or []
    n = int(res.get("total_trades") or 0)
    pnl = float(res.get("total_pnl") or 0)
    wins = [t for t in trades if float(t.get("pnl") or 0) > 0]
    losses = [t for t in trades if float(t.get("pnl") or 0) <= 0]
    rs = []
    for t in trades:
        entry = float(t.get("entry_price") or 0)
        stop = float(t.get("stoploss") or 0)
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        rs.append(float(t.get("pnl") or 0) / (risk * max(int(t.get("qty") or 1), 1)))
    reasons = {}
    for t in trades:
        reasons[str(t.get("exit_reason") or "unknown")] = reasons.get(str(t.get("exit_reason") or "unknown"), 0) + 1
    dow = {d: [] for d in range(5)}
    for t in trades:
        try:
            import pandas as pd

            ts = pd.to_datetime(t.get("entry_ts"), errors="coerce")
            if ts is not None and not pd.isna(ts):
                if getattr(ts, "tzinfo", None) is not None:
                    ts = ts.tz_convert("Asia/Kolkata") if ts.tzinfo else ts
                dow[int(ts.weekday())].append(t)
        except Exception:
            pass

    def subset(rows):
        if not rows:
            return {"n": 0, "wr": None, "pnl": 0.0, "pf": None, "exp": None}
        w = [x for x in rows if float(x.get("pnl") or 0) > 0]
        l = [x for x in rows if float(x.get("pnl") or 0) <= 0]
        p = sum(float(x.get("pnl") or 0) for x in rows)
        gp = sum(float(x.get("pnl") or 0) for x in w)
        gl = abs(sum(float(x.get("pnl") or 0) for x in l))
        return {
            "n": len(rows),
            "wr": round(len(w) / len(rows) * 100, 2),
            "pnl": round(p, 2),
            "pf": round(gp / gl, 2) if gl else round(gp, 2),
            "exp": round(p / len(rows), 2),
        }

    mw, ml = streaks(trades)
    import statistics

    return {
        "trades": n,
        "win_rate": float(res.get("win_rate") or 0),
        "profit_factor": float(res.get("profit_factor") or 0),
        "expectancy": round(pnl / n, 2) if n else 0.0,
        "total_pnl": pnl,
        "max_drawdown": float(res.get("max_drawdown") or 0),
        "avg_win": round(sum(float(t["pnl"]) for t in wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(float(t["pnl"]) for t in losses) / len(losses), 2) if losses else 0.0,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "max_consec_wins": mw,
        "max_consec_losses": ml,
        "avg_r": round(sum(rs) / len(rs), 3) if rs else 0.0,
        "median_r": round(statistics.median(rs), 3) if rs else 0.0,
        "exit_reasons": reasons,
        "dow": {
            "Mon": subset(dow[0]),
            "Tue": subset(dow[1]),
            "Wed": subset(dow[2]),
            "Thu": subset(dow[3]),
            "Fri": subset(dow[4]),
        },
        "picked_stocks": res.get("picked_stocks"),
    }


def score(m, ref_n=20):
    n = m["trades"]
    wr = float(m["win_rate"])
    pf = min(float(m["profit_factor"] or 0), 4.0)
    exp = float(m["expectancy"] or 0)
    pnl = float(m["total_pnl"] or 0)
    dd = float(m["max_drawdown"] or 0)
    avg_r = float(m.get("avg_r") or 0)
    if n < MIN_TRADES:
        return -100.0 + n + wr * 0.05
    if exp <= 0:
        return wr * 0.5 + pf - 25
    trade_sc = max(0.0, min(n / max(ref_n, 1), 2.5)) * 10
    return wr * 2.2 + pf * 12 + max(min(exp / 80, 18), -12) + trade_sc + max(min(pnl / 2500, 14), -10) + max(min(avg_r * 8, 10), -5) - min(dd / 2.0, 25)


def main() -> int:
    t0 = time.time()
    payload = load_frames()
    frames = payload["frames"]
    base = baseline_params()
    print(f"=== {STRATEGY_CODE} symbols={len(frames)} {payload['from_date']}→{payload['to_date']} ===", flush=True)

    # Prefer symbols that actually fire baseline ORB; fall back to full universe.
    active = []
    from trading_shared.strategies.intraday_desk.backtest import run_intraday_strategy_backtest

    for sym, df in frames:
        r = run_intraday_strategy_backtest(df, STRATEGY_CODE, sym, params=base)
        if int(r.get("total_trades") or 0) > 0:
            active.append((sym, df))
    use_frames = active if len(active) >= 5 else frames
    picks = [{"symbol": sym, "score": 1.0} for sym, _ in use_frames]
    print(f"Active ORB symbols={len(use_frames)} / {len(frames)}", flush=True)
    print("Picks:", [p["symbol"] for p in picks], flush=True)

    print("\n--- BASELINE ---", flush=True)
    base_full = metrics(run_universe(use_frames, base, picks=picks))
    train = split_frames(use_frames, 0.0, 0.6)
    val = split_frames(use_frames, 0.6, 0.8)
    oos = split_frames(use_frames, 0.8, 1.0)
    base_train = metrics(run_universe(train, base, picks=picks))
    base_val = metrics(run_universe(val, base, picks=picks))
    base_oos = metrics(run_universe(oos, base, picks=picks))
    print(json.dumps({"full": base_full, "train": base_train, "val": base_val, "oos": base_oos}, indent=2, default=str), flush=True)

    rows = []
    work = deepcopy(base)
    ref_n = max(base_train["trades"], 8)

    def ev(label, group, params, dataset="train"):
        data = {"train": train, "val": val, "oos": oos, "full": use_frames}[dataset]
        m = metrics(run_universe(data, params, picks=picks))
        sc = score(m, ref_n)
        row = {"label": label, "group": group, "dataset": dataset, "params": dict(params), "metrics": m, "score": round(sc, 2)}
        rows.append(row)
        print(
            f"{group:10} {label:28} [{dataset}] n={m['trades']:>3} WR={m['win_rate']:>6}% "
            f"PF={m['profit_factor']:>6} EXP={m['expectancy']:>8} PnL={m['total_pnl']:>9} "
            f"DD={m['max_drawdown']:>6} R={m['avg_r']:>5} sc={sc:>6.1f}",
            flush=True,
        )
        return row

    def best(group):
        g = [r for r in rows if r["group"] == group and r["dataset"] == "train" and r["metrics"]["trades"] >= MIN_TRADES]
        pos = [r for r in g if r["metrics"]["expectancy"] > 0]
        pool = pos or g or [r for r in rows if r["group"] == group and r["dataset"] == "train"]
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
        print("LOCK", group, {k: work.get(k) for k in keys}, flush=True)

    # 1 OR duration
    print("\n--- 1 OR duration ---", flush=True)
    for mins in [15, 20, 25, 30, 35, 40, 45]:
        p = deepcopy(work)
        p["or_end_min"] = 9 * 60 + 15 + mins
        # Keep entry start at OR end if currently equal to old OR end.
        if int(work["entry_start_min"]) <= int(p["or_end_min"]):
            p["entry_start_min"] = int(p["or_end_min"])
        ev(f"or_{mins}m", "or_dur", p)
    lock("or_dur", "or_end_min", "entry_start_min")

    # 2-5 OR width
    print("\n--- 2-5 OR width ---", flush=True)
    for mn in [0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]:
        p = deepcopy(work); p["min_or_width_pct"] = mn; ev(f"wmin_{mn}", "wmin", p)
    lock("wmin", "min_or_width_pct")
    for mx in [0.80, 1.00, 1.20, 1.40, 1.60, 1.80, 2.00, 2.25]:
        p = deepcopy(work); p["max_or_width_pct"] = mx; ev(f"wmax_{mx}", "wmax", p)
    lock("wmax", "max_or_width_pct")
    for mn, mx in [(0.20, 1.20), (0.25, 1.20), (0.25, 1.40), (0.30, 1.40), (0.30, 1.60), (0.35, 1.50)]:
        p = deepcopy(work); p["min_or_width_pct"] = mn; p["max_or_width_pct"] = mx; ev(f"w_{mn}_{mx}", "wwidth", p)
    lock("wwidth", "min_or_width_pct", "max_or_width_pct")

    # 6 buffer
    print("\n--- 6 Buffer ---", flush=True)
    for b in [0.0, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.15, 0.20]:
        p = deepcopy(work); p["breakout_buffer_pct"] = b; ev(f"buf_{b}", "buffer", p)
    lock("buffer", "breakout_buffer_pct")

    # 7 candle / first breakout
    print("\n--- 7-8 Candle / first break ---", flush=True)
    for body, hi in [(0.0, False), (0.0, True), (0.40, False), (0.50, False), (0.60, False)]:
        p = deepcopy(work); p["candle_body_min"] = body; p["require_high_break"] = hi
        ev(f"cndl_{body}_{hi}", "candle", p)
    lock("candle", "candle_body_min", "require_high_break")
    for mode in ["prev_close_inside", "prev_bar_inside", "prev_not_above"]:
        p = deepcopy(work); p["first_breakout_mode"] = mode; ev(f"fb_{mode}", "first", p)
    lock("first", "first_breakout_mode")

    # 9-11 volume
    print("\n--- 9-11 Volume ---", flush=True)
    for v in [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.75, 2.0, 2.25]:
        p = deepcopy(work); p["vol_mult"] = v; ev(f"vol_{v}", "vol", p)
    lock("vol", "vol_mult")
    for lb in [10, 15, 20, 25, 30, 40]:
        p = deepcopy(work); p["vol_lookback"] = lb; ev(f"vlb_{lb}", "vlook", p)
    lock("vlook", "vol_lookback")
    for rising in [False, True]:
        p = deepcopy(work); p["require_vol_rising"] = rising; ev(f"vrise_{rising}", "vrise", p)
    lock("vrise", "require_vol_rising")

    # 12-14 EMA
    print("\n--- 12-14 EMA ---", flush=True)
    for ep in [9, 13, 15, 20, 21, 25, 30, 34, 50]:
        p = deepcopy(work); p["ema_period"] = ep; ev(f"ema_{ep}", "ema", p)
    lock("ema", "ema_period")
    for slope in [False, True]:
        p = deepcopy(work); p["ema_slope"] = slope; ev(f"slope_{slope}", "eslope", p)
    lock("eslope", "ema_slope")
    for d in [0.0, 0.02, 0.05, 0.10, 0.15, 0.20]:
        p = deepcopy(work); p["ema_min_dist_pct"] = d; ev(f"edist_{d}", "edist", p)
    lock("edist", "ema_min_dist_pct")

    # 15-16 window
    print("\n--- 15-16 Entry window ---", flush=True)
    for start in [9 * 60 + 40, 9 * 60 + 45, 9 * 60 + 50, 9 * 60 + 55, 10 * 60, 10 * 60 + 5, 10 * 60 + 15]:
        if start < int(work["or_end_min"]):
            continue
        p = deepcopy(work); p["entry_start_min"] = start; ev(f"start_{start}", "start", p)
    lock("start", "entry_start_min")
    for end in [10 * 60 + 30, 10 * 60 + 45, 11 * 60, 11 * 60 + 15, 11 * 60 + 30, 11 * 60 + 45, 12 * 60]:
        p = deepcopy(work); p["entry_end_min"] = end; ev(f"end_{end}", "end", p)
    lock("end", "entry_end_min")

    # 18-20 stop / risk / target
    print("\n--- 18-20 Stop/Risk/Target ---", flush=True)
    for method in ["or_mid", "or_low"]:
        p = deepcopy(work); p["stop_method"] = method; ev(f"stop_{method}", "stopm", p)
    for pct in [0.20, 0.30, 0.40, 0.50, 0.60]:
        p = deepcopy(work); p["stop_method"] = "pct"; p["stop_pct"] = pct; ev(f"stop_pct_{pct}", "stopm", p)
    for am in [0.5, 0.75, 1.0, 1.25, 1.5]:
        p = deepcopy(work); p["stop_method"] = "atr"; p["stop_atr_mult"] = am; ev(f"stop_atr_{am}", "stopm", p)
    lock("stopm", "stop_method", "stop_pct", "stop_atr_mult")
    for rc in [0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00]:
        p = deepcopy(work); p["max_risk_pct"] = rc; ev(f"risk_{rc}", "risk", p)
    lock("risk", "max_risk_pct")
    for rr in [1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0]:
        p = deepcopy(work); p["min_rr"] = rr; ev(f"rr_{rr}", "target", p)
    lock("target", "min_rr")

    # 22-23 trail / force exit
    print("\n--- 22-23 Trail / force exit ---", flush=True)
    for after, atrm in [(0.0, 0.0), (1.0, 0.75), (1.0, 1.0), (1.5, 1.0)]:
        p = deepcopy(work); p["trail_after_r"] = after; p["trail_atr_mult"] = atrm; ev(f"trail_{after}_{atrm}", "trail", p)
    lock("trail", "trail_after_r", "trail_atr_mult")
    for fe in [14 * 60 + 45, 15 * 60, 15 * 60 + 15, 15 * 60 + 20, 15 * 60 + 25]:
        p = deepcopy(work); p["force_exit_min"] = fe; ev(f"fe_{fe}", "force", p)
    lock("force", "force_exit_min")

    # 29 retest
    print("\n--- 29 Retest ---", flush=True)
    for mode in ["off", "require"]:
        p = deepcopy(work); p["retest_mode"] = mode; ev(f"retest_{mode}", "retest", p)
    lock("retest", "retest_mode")

    # Stability
    print("\n--- Stability ---", flush=True)
    for db in [-0.02, -0.01, 0.0, 0.01, 0.02]:
        p = deepcopy(work); p["breakout_buffer_pct"] = max(0.0, float(work["breakout_buffer_pct"]) + db); ev(f"stab_buf_{p['breakout_buffer_pct']:.3f}", "stability", p)
    for dv in [-0.1, 0.0, 0.1]:
        p = deepcopy(work); p["vol_mult"] = max(1.0, float(work["vol_mult"]) + dv); ev(f"stab_vol_{p['vol_mult']:.2f}", "stability", p)
    for drr in [-0.25, 0.0, 0.25]:
        p = deepcopy(work); p["min_rr"] = max(1.0, float(work["min_rr"]) + drr); ev(f"stab_rr_{p['min_rr']}", "stability", p)

    # Combos + WF
    print("\n--- Combos / WF ---", flush=True)
    combos = [deepcopy(base), deepcopy(work)]
    for d_buf, d_vol, d_rr in [(-0.02, 0.0, 0.0), (0.0, 0.1, 0.0), (0.0, 0.0, -0.25), (0.02, -0.1, 0.25)]:
        p = deepcopy(work)
        p["breakout_buffer_pct"] = max(0.0, float(p["breakout_buffer_pct"]) + d_buf)
        p["vol_mult"] = max(1.0, float(p["vol_mult"]) + d_vol)
        p["min_rr"] = max(1.0, float(p["min_rr"]) + d_rr)
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
            1 if r["metrics"]["win_rate"] >= base_train["win_rate"] else 0,
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
    ranked_rows = sorted(eligible, key=lambda r: r["score"], reverse=True)

    report = {
        "strategy": STRATEGY_CODE,
        "data_source": payload.get("source"),
        "date_range": {"from": payload["from_date"], "to": payload["to_date"]},
        "symbols": len(frames),
        "picks": [p["symbol"] for p in picks],
        "elapsed_sec": round(time.time() - t0, 1),
        "baseline": {"params": base, "full": base_full, "train": base_train, "val": base_val, "oos": base_oos},
        "working_params": work,
        "top10_train": ranked_rows[:10],
        "recommended": recommended,
        "recommended_oos": rec_oos,
        "recommended_full": rec_full,
        "notes": [
            "Long-only ORB retained; shorts not enabled.",
            "Partial exits not supported by engine — skipped.",
            "Picks fixed from baseline universe ranking for OFAT stability.",
        ],
    }
    out = os.environ.get("REPORT_PATH", "/tmp/optimize_intra_orb_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote {out} elapsed={report['elapsed_sec']}s", flush=True)
    print("\n=== TOP 10 TRAIN ===", flush=True)
    for i, r in enumerate(ranked_rows[:10], 1):
        m = r["metrics"]
        print(f"{i:2}. [{r['group']}] {r['label']} sc={r['score']} WR={m['win_rate']}% PF={m['profit_factor']} EXP={m['expectancy']} tr={m['trades']} PnL={m['total_pnl']}", flush=True)
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
