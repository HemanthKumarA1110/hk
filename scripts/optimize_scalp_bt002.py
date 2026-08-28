#!/usr/bin/env python3
"""SCALP-BT-002 (ORB Breakout) parameter optimization — Bank Nifty.

Uses existing run_strategy_backtest. Does not modify strategy defaults.

Usage (inside strategy-engine):

    PYTHONUNBUFFERED=1 python /app/scripts/optimize_scalp_bt002.py

Env:
    BACKTEST_DAYS=60
    BACKTEST_USER_ID=1
    BACKTEST_CAPITAL=100000
    SAMPLE_BARS=25000
    CANDLE_CACHE=/tmp/bt002_candles.pkl
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

STRATEGY_CODE = "SCALP-BT-002"
INSTRUMENT_KEY = "banknifty"
BACKTEST_DAYS = int(os.environ.get("BACKTEST_DAYS", "60"))
SAMPLE_BARS = int(os.environ.get("SAMPLE_BARS", "25000"))
MIN_TRADES = int(os.environ.get("MIN_TRADES", "3"))
CANDLE_CACHE = os.environ.get("CANDLE_CACHE", "/tmp/bt002_candles.pkl")

BUFFER_POINTS = [0, 2, 3, 5, 7, 10, 12, 15]
OR_MINS = [80, 100, 120, 140]
OR_MAXS = [160, 180, 200, 220, 240]
CALL_RSI = [(50, 65), (52, 66), (54, 68), (55, 68), (56, 70), (52, 70)]
PUT_RSI = [(30, 46), (32, 46), (34, 48), (32, 44), (35, 47), (30, 45)]
VOL_RATIOS = [1.00, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35, 1.40, 1.50, 1.60]
# Existing param: morning cutoff 10:30 blocks afternoon ORB; 14:45 enables afternoon window.
CUTOFFS = [10 * 60 + 30, 14 * 60 + 45]


async def load_candles(user_id: int):
    import trading_shared.strategies.scalping_desk.service as svc_mod
    from trading_shared.db.session import SessionLocal
    from trading_shared.strategies.scalping_desk.service import ScalpingDeskService

    svc_mod.BACKTEST_CHUNK_DELAY_SEC = float(os.environ.get("BACKTEST_CHUNK_DELAY_SEC", "1.5"))
    to_date = date.today()
    from_date = (to_date - timedelta(days=BACKTEST_DAYS)).isoformat()
    db = SessionLocal()
    try:
        svc = ScalpingDeskService(db, user_id, INSTRUMENT_KEY)
        df, source, notes = await svc._load_desk_backtest_candles(
            from_date, to_date.isoformat(), "1m"
        )
        if notes:
            print("notes:", "; ".join(notes), flush=True)
        if len(df) > SAMPLE_BARS:
            df = df.tail(SAMPLE_BARS).reset_index(drop=True)
        return df, source, from_date, to_date.isoformat()
    finally:
        db.close()


def get_candles(user_id: int):
    if os.path.isfile(CANDLE_CACHE) and os.environ.get("FORCE_RELOAD") != "1":
        with open(CANDLE_CACHE, "rb") as f:
            payload = pickle.load(f)
        print(
            f"Loaded cache {CANDLE_CACHE}: bars={len(payload['df']):,} source={payload['source']}",
            flush=True,
        )
        return payload["df"], payload["source"], payload["from_date"], payload["to_date"]

    df, source, from_date, to_date = asyncio.run(load_candles(user_id))
    with open(CANDLE_CACHE, "wb") as f:
        pickle.dump(
            {"df": df, "source": source, "from_date": from_date, "to_date": to_date},
            f,
        )
    print(f"Cached candles → {CANDLE_CACHE}", flush=True)
    return df, source, from_date, to_date


def spot_ref(candles) -> float:
    closes = candles["close"].astype(float)
    return float(closes.median()) if len(closes) else 57000.0


def pts_to_pct(pts: float, spot: float) -> float:
    return float(pts) / max(spot, 1.0)


def baseline_params() -> dict[str, Any]:
    from trading_shared.strategies.scalping_desk.orb_breakout_tuning import ORB_BREAKOUT_BANK_DEFAULTS

    return dict(ORB_BREAKOUT_BANK_DEFAULTS)


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


def trade_breakdown(result: dict[str, Any]) -> dict[str, Any]:
    trades = result.get("trades") or []
    if not trades:
        return {
            "call_wr": None,
            "put_wr": None,
            "morning_wr": None,
            "afternoon_wr": None,
            "call_n": 0,
            "put_n": 0,
            "morning_n": 0,
            "afternoon_n": 0,
        }

    def wr(rows):
        if not rows:
            return None
        wins = sum(1 for t in rows if float(t.get("pnl") or 0) > 0)
        return round(wins / len(rows) * 100, 2)

    calls = [t for t in trades if str(t.get("signal_type")).upper() == "CALL"]
    puts = [t for t in trades if str(t.get("signal_type")).upper() == "PUT"]
    morning, afternoon = [], []
    for t in trades:
        ts = str(t.get("entry_time") or "")
        hhmm = None
        if "T" in ts:
            try:
                part = ts.split("T")[1][:5]
                hh, mm = part.split(":")
                hhmm = int(hh) * 60 + int(mm)
            except Exception:
                pass
        elif " " in ts:
            try:
                part = ts.split(" ")[1][:5]
                hh, mm = part.split(":")
                hhmm = int(hh) * 60 + int(mm)
            except Exception:
                pass
        if hhmm is None:
            continue
        if 9 * 60 + 20 <= hhmm <= 10 * 60 + 30:
            morning.append(t)
        elif 13 * 60 + 30 <= hhmm <= 14 * 60 + 45:
            afternoon.append(t)

    return {
        "call_wr": wr(calls),
        "put_wr": wr(puts),
        "morning_wr": wr(morning),
        "afternoon_wr": wr(afternoon),
        "call_n": len(calls),
        "put_n": len(puts),
        "morning_n": len(morning),
        "afternoon_n": len(afternoon),
    }


def metrics(result: dict[str, Any]) -> dict[str, Any]:
    trades = int(result.get("total_trades") or 0)
    pnl = float(result.get("total_pnl") or 0)
    wr = float(result.get("win_rate") or 0)
    pf = float(result.get("profit_factor") or 0)
    dd = float(result.get("max_drawdown") or 0)
    expectancy = round(pnl / trades, 2) if trades else 0.0
    bd = trade_breakdown(result)
    return {
        "trades": trades,
        "win_rate": wr,
        "profit_factor": pf,
        "expectancy": expectancy,
        "total_pnl": pnl,
        "max_drawdown": dd,
        **bd,
    }


def balanced_score(m: dict[str, Any], baseline_trades: int) -> float:
    trades = m["trades"]
    if trades < MIN_TRADES:
        return -100.0 + trades

    wr = m["win_rate"]
    pf = min(float(m["profit_factor"] or 0), 3.0)
    exp = float(m["expectancy"] or 0)
    dd = float(m["max_drawdown"] or 0)
    pnl = float(m["total_pnl"] or 0)

    trade_ratio = trades / max(baseline_trades, 1)
    trade_score = max(0.0, min(trade_ratio, 2.0)) * 12.0
    if trade_ratio < 0.67:
        trade_score -= 15.0
    # Soft reward for more samples when baseline is thin
    if baseline_trades < 10 and trades >= baseline_trades:
        trade_score += min(trades - baseline_trades, 10) * 1.5

    dd_penalty = min(dd / 1000.0, 40.0)
    exp_score = max(min(exp / 200.0, 20.0), -20.0)
    pnl_score = max(min(pnl / 5000.0, 15.0), -15.0)

    return wr * 1.8 + pf * 18.0 + exp_score + trade_score + pnl_score - dd_penalty


def stability_flag(scores_nearby: list[float], best: float) -> bool:
    if len(scores_nearby) < 2:
        return False
    others = [s for s in scores_nearby if abs(s - best) > 1e-9]
    if not others:
        return False
    avg = sum(others) / len(others)
    return best - avg > 25.0


def main() -> int:
    import trading_shared.strategies.scalping_desk.backtest as bt
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

    bt.MAX_BACKTEST_BARS = int(os.environ.get("MAX_BACKTEST_BARS", "30000"))

    user_id = int(os.environ.get("BACKTEST_USER_ID", "1"))
    capital = float(os.environ.get("BACKTEST_CAPITAL", "100000"))
    lot = int(INSTRUMENTS[INSTRUMENT_KEY]["lot_size"])

    print(f"=== Optimize {STRATEGY_CODE} · {BACKTEST_DAYS}d ===", flush=True)
    try:
        candles, source, from_date, to_date = get_candles(user_id)
    except Exception as exc:
        print(f"FAILED load: {exc}", flush=True)
        return 1

    print(f"bars={len(candles):,} source={source} range={from_date}→{to_date}", flush=True)
    if len(candles) < 500:
        print("Insufficient bars", flush=True)
        return 1

    spot = spot_ref(candles)
    print(f"spot_ref={spot:.2f} (for buffer pts→pct)", flush=True)

    base = baseline_params()
    print("\n--- BASELINE (unchanged) ---", flush=True)
    base_result = run_bt(candles, lot, capital, base)
    base_m = metrics(base_result)
    base_score = balanced_score(base_m, max(base_m["trades"], 1))
    print(json.dumps({"params": base, "metrics": base_m, "score": round(base_score, 2)}, indent=2), flush=True)

    rows: list[dict[str, Any]] = []

    def evaluate(label: str, group: str, orb: dict[str, Any]) -> dict[str, Any]:
        result = run_bt(candles, lot, capital, orb)
        m = metrics(result)
        sc = balanced_score(m, max(base_m["trades"], 1))
        row = {
            "label": label,
            "group": group,
            "params": {k: orb[k] for k in sorted(orb) if str(k).startswith("orb_")},
            "metrics": m,
            "score": round(sc, 2),
        }
        rows.append(row)
        print(
            f"{group:12} {label:28} trades={m['trades']:>3} WR={m['win_rate']:>5}% "
            f"PF={m['profit_factor']:>5} EXP={m['expectancy']:>8} "
            f"PnL={m['total_pnl']:>9} DD={m['max_drawdown']:>8} score={sc:>6.1f}",
            flush=True,
        )
        return row

    print("\n--- OFAT OR range ---", flush=True)
    for rmin, rmax in product(OR_MINS, OR_MAXS):
        if rmin >= rmax:
            continue
        orb = deepcopy(base)
        orb.update({"orb_or_range_min": float(rmin), "orb_or_range_max": float(rmax), "orb_skip_wide_or": True})
        evaluate(f"or_{rmin}_{rmax}", "or_range", orb)

    print("\n--- OFAT buffer (points → orb_buffer_pct) ---", flush=True)
    for pts in BUFFER_POINTS:
        orb = deepcopy(base)
        orb["orb_buffer_pct"] = pts_to_pct(pts, spot)
        evaluate(f"buf_{pts}pts", "buffer", orb)

    print("\n--- OFAT CALL RSI ---", flush=True)
    for lo, hi in CALL_RSI:
        orb = deepcopy(base)
        orb.update({"orb_rsi_call_min": lo, "orb_rsi_call_max": hi})
        evaluate(f"call_rsi_{lo}_{hi}", "call_rsi", orb)

    print("\n--- OFAT PUT RSI ---", flush=True)
    for lo, hi in PUT_RSI:
        orb = deepcopy(base)
        orb.update({"orb_rsi_put_min": lo, "orb_rsi_put_max": hi})
        evaluate(f"put_rsi_{lo}_{hi}", "put_rsi", orb)

    print("\n--- OFAT volume ---", flush=True)
    for v in VOL_RATIOS:
        orb = deepcopy(base)
        orb["orb_vol_min"] = float(v)
        orb["orb_use_vol_spike"] = False
        evaluate(f"vol_{v:.2f}", "volume", orb)

    print("\n--- OFAT momentum (boolean; ATR thresholds not in code) ---", flush=True)
    for flag in (True, False):
        orb = deepcopy(base)
        orb["orb_require_two_bar_momentum"] = flag
        evaluate(f"mom_{flag}", "momentum", orb)

    print("\n--- OFAT entry cutoff (afternoon enable) ---", flush=True)
    for cut in CUTOFFS:
        orb = deepcopy(base)
        orb["orb_entry_cutoff_min"] = cut
        evaluate(f"cutoff_{cut}", "cutoff", orb)

    print("\n--- Ablation ---", flush=True)
    ablations = [
        ("no_inside_or", {"orb_require_inside_or": False}),
        ("no_momentum", {"orb_require_two_bar_momentum": False}),
        ("no_vol_filter", {"orb_vol_min": 0.0}),
        ("no_buffer", {"orb_buffer_pct": 0.0}),
        ("wide_rsi", {"orb_rsi_call_min": 40, "orb_rsi_call_max": 80, "orb_rsi_put_min": 20, "orb_rsi_put_max": 60}),
        ("loose_or_range", {"orb_or_range_min": 80.0, "orb_or_range_max": 300.0, "orb_skip_wide_or": True}),
        ("afternoon_on", {"orb_entry_cutoff_min": 14 * 60 + 45}),
        ("afternoon_no_inside", {"orb_entry_cutoff_min": 14 * 60 + 45, "orb_require_inside_or": False}),
    ]
    for name, tweak in ablations:
        orb = deepcopy(base)
        orb.update(tweak)
        evaluate(name, "ablation", orb)

    def best_in_group(group: str) -> dict[str, Any] | None:
        g = [r for r in rows if r["group"] == group and r["metrics"]["trades"] >= MIN_TRADES]
        if not g:
            return None
        return max(g, key=lambda r: r["score"])

    best_or = best_in_group("or_range")
    best_buf = best_in_group("buffer")
    best_call = best_in_group("call_rsi")
    best_put = best_in_group("put_rsi")
    best_vol = best_in_group("volume")
    best_mom = best_in_group("momentum")
    best_cut = best_in_group("cutoff")

    print("\n--- Best OFAT picks ---", flush=True)
    for name, row in [
        ("OR", best_or),
        ("BUF", best_buf),
        ("CALL", best_call),
        ("PUT", best_put),
        ("VOL", best_vol),
        ("MOM", best_mom),
        ("CUT", best_cut),
    ]:
        if row:
            print(f"  {name}: {row['label']} score={row['score']} WR={row['metrics']['win_rate']} trades={row['metrics']['trades']}", flush=True)

    print("\n--- Refined combinations ---", flush=True)

    def take_or(row):
        if not row:
            return float(base["orb_or_range_min"]), float(base["orb_or_range_max"])
        return float(row["params"]["orb_or_range_min"]), float(row["params"]["orb_or_range_max"])

    or_min_b, or_max_b = take_or(best_or)
    buf_pct = float(best_buf["params"]["orb_buffer_pct"]) if best_buf else float(base["orb_buffer_pct"])
    call_lo = int(best_call["params"]["orb_rsi_call_min"]) if best_call else int(base["orb_rsi_call_min"])
    call_hi = int(best_call["params"]["orb_rsi_call_max"]) if best_call else int(base["orb_rsi_call_max"])
    put_lo = int(best_put["params"]["orb_rsi_put_min"]) if best_put else int(base["orb_rsi_put_min"])
    put_hi = int(best_put["params"]["orb_rsi_put_max"]) if best_put else int(base["orb_rsi_put_max"])
    vol_b = float(best_vol["params"]["orb_vol_min"]) if best_vol else float(base["orb_vol_min"])
    mom_b = bool(best_mom["params"]["orb_require_two_bar_momentum"]) if best_mom else True
    cut_b = int(best_cut["params"]["orb_entry_cutoff_min"]) if best_cut else int(base["orb_entry_cutoff_min"])

    # Compact refined grid around OFAT winners + stability neighbours (keep runtime bounded).
    or_min_opts = sorted({120.0, or_min_b})
    or_max_opts = sorted({200.0, or_max_b})
    vol_opts = sorted({1.35, vol_b})
    cut_opts = sorted({int(base["orb_entry_cutoff_min"]), cut_b})
    buf_opts = sorted({float(base["orb_buffer_pct"]), buf_pct, pts_to_pct(3, spot), pts_to_pct(5, spot)})

    combo_candidates: list[dict[str, Any]] = []
    for rmin, rmax, vol, cut, bpct in product(or_min_opts, or_max_opts, vol_opts, cut_opts, buf_opts):
        if rmin >= rmax:
            continue
        orb = deepcopy(base)
        orb.update(
            {
                "orb_or_range_min": float(rmin),
                "orb_or_range_max": float(rmax),
                "orb_skip_wide_or": True,
                "orb_buffer_pct": float(bpct),
                "orb_rsi_call_min": call_lo,
                "orb_rsi_call_max": call_hi,
                "orb_rsi_put_min": put_lo,
                "orb_rsi_put_max": put_hi,
                "orb_vol_min": float(vol),
                "orb_require_two_bar_momentum": mom_b,
                "orb_require_inside_or": True,
                "orb_entry_cutoff_min": int(cut),
            }
        )
        combo_candidates.append(orb)

    # High-value focused set from first-pass findings
    focused = [
        {"orb_buffer_pct": pts_to_pct(3, spot), "orb_rsi_put_min": 34, "orb_rsi_put_max": 48},
        {"orb_buffer_pct": pts_to_pct(5, spot), "orb_or_range_min": 120.0, "orb_or_range_max": 200.0},
        {
            "orb_buffer_pct": pts_to_pct(3, spot),
            "orb_entry_cutoff_min": 14 * 60 + 45,
            "orb_or_range_min": 120.0,
            "orb_or_range_max": 200.0,
        },
        {
            "orb_buffer_pct": pts_to_pct(5, spot),
            "orb_entry_cutoff_min": 14 * 60 + 45,
            "orb_vol_min": 1.25,
            "orb_rsi_call_min": 52,
            "orb_rsi_call_max": 70,
            "orb_rsi_put_min": 34,
            "orb_rsi_put_max": 48,
        },
        {
            "orb_buffer_pct": pts_to_pct(3, spot),
            "orb_entry_cutoff_min": 14 * 60 + 45,
            "orb_require_inside_or": True,
            "orb_vol_min": 1.35,
            "orb_or_range_min": 100.0,
            "orb_or_range_max": 200.0,
        },
        {
            "orb_buffer_pct": pts_to_pct(3, spot),
            "orb_entry_cutoff_min": 14 * 60 + 45,
            "orb_or_range_min": 120.0,
            "orb_or_range_max": 200.0,
            "orb_rsi_call_min": 52,
            "orb_rsi_call_max": 66,
            "orb_rsi_put_min": 35,
            "orb_rsi_put_max": 47,
        },
    ]
    for tweak in focused:
        orb = deepcopy(base)
        orb.update(tweak)
        combo_candidates.append(orb)

    combo_candidates.append(deepcopy(base))

    seen: set[str] = set()
    unique_combos: list[dict[str, Any]] = []
    for orb in combo_candidates:
        key = json.dumps(orb, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        unique_combos.append(orb)

    print(f"combo count={len(unique_combos)}", flush=True)
    for i, orb in enumerate(unique_combos):
        evaluate(f"combo_{i}", "combo", orb)

    eligible = [r for r in rows if r["metrics"]["trades"] >= MIN_TRADES]
    ranked = sorted(eligible, key=lambda r: r["score"], reverse=True)

    # Prefer recommendations that are not pure overfitting on n<=4 unless clearly better
    def recommend(ranked_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not ranked_rows:
            return None
        # Prefer combo/focused with trades >= baseline and WR>=baseline, PF not collapsing
        base_wr = base_m["win_rate"]
        base_pf = base_m["profit_factor"]
        preferred = [
            r
            for r in ranked_rows
            if r["metrics"]["win_rate"] >= base_wr - 5
            and r["metrics"]["profit_factor"] >= min(base_pf, 2.0) * 0.5
            and r["metrics"]["expectancy"] > 0
            and r["metrics"]["trades"] >= base_m["trades"]
        ]
        pool = preferred or ranked_rows
        # Among top scores, prefer higher trade count for stability when score within 5 pts
        top_score = pool[0]["score"]
        near = [r for r in pool if r["score"] >= top_score - 5]
        return max(near, key=lambda r: (r["score"], r["metrics"]["trades"], r["metrics"]["win_rate"]))

    top = recommend(ranked)
    overfit = False
    if top and top["group"] in ("combo", "or_range", "buffer"):
        nearby = [r["score"] for r in rows if r["group"] == top["group"]]
        overfit = stability_flag(nearby, top["score"])

    report = {
        "strategy": STRATEGY_CODE,
        "instrument": INSTRUMENT_KEY,
        "data_source": source,
        "date_range": {"from": from_date, "to": to_date},
        "bars": len(candles),
        "spot_ref": spot,
        "baseline": {"params": base, "metrics": base_m, "score": round(base_score, 2)},
        "top10": ranked[:10],
        "recommended": top,
        "possible_overfitting": overfit,
        "notes": [
            "Momentum ATR thresholds are not implemented in SCALP-BT-002; tested ON/OFF only.",
            "EMA confirmation and candle color are hard-coded in evaluate_orb_breakout; not ablated.",
            "Prior-close-inside-OR is not a separate flag (prior-bar-inside-OR / orb_require_inside_or exists).",
            "orb_entry_cutoff_min=630 (10:30) blocks afternoon battle window; cutoff=885 enables 13:30–14:45.",
            "Sample size is small under tight filters — treat n<10 as low statistical confidence.",
            "Buffer tested in absolute points converted to orb_buffer_pct via median spot.",
        ],
    }

    out_path = os.environ.get("REPORT_PATH", "/tmp/optimize_scalp_bt002_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote report → {out_path}", flush=True)

    print("\n=== TOP 10 ===", flush=True)
    for i, r in enumerate(ranked[:10], 1):
        m = r["metrics"]
        print(
            f"{i:2}. [{r['group']}] {r['label']} score={r['score']} "
            f"WR={m['win_rate']}% PF={m['profit_factor']} EXP={m['expectancy']} "
            f"trades={m['trades']} PnL={m['total_pnl']} DD={m['max_drawdown']}",
            flush=True,
        )

    if top:
        print("\n=== RECOMMENDED ===", flush=True)
        print(
            json.dumps({"label": top["label"], "params": top["params"], "metrics": top["metrics"]}, indent=2),
            flush=True,
        )
        print(f"possible_overfitting={overfit}", flush=True)

        # Convenience: buffer pts from pct
        rec_buf_pct = float(top["params"].get("orb_buffer_pct") or 0)
        print(f"recommended_buffer_pts≈{rec_buf_pct * spot:.1f}", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
