#!/usr/bin/env python3
"""OFAT + walk-forward for INTRA-VWAP-ORB on Angel One 5m equity data.

Loads last N days (default 180 ≈ 6 months) via chunked Angel One fetches,
falls back to DB only when coverage is sufficient. Caches frames to pickle.

    BACKTEST_USER_ID=1 BACKTEST_DAYS=180 \\
      PYTHONUNBUFFERED=1 python /tmp/optimize_intra_vwap_orb.py
"""

from __future__ import annotations

import asyncio
import json
import os
import pickle
import sys
import time
from copy import deepcopy
from datetime import date, datetime, timedelta
from typing import Any

STRATEGY_CODE = "INTRA-VWAP-ORB"
MIN_TRADES = int(os.environ.get("MIN_TRADES", "15"))
TOP_N = int(os.environ.get("BACKTEST_TOP_N", "0"))  # 0 = all loaded symbols
CAPITAL = float(os.environ.get("BACKTEST_CAPITAL", "100000"))
CACHE = os.environ.get("CANDLE_CACHE", "/tmp/intra_vwap_orb_frames.pkl")
SYMBOL_LIMIT = int(os.environ.get("SYMBOL_LIMIT", "25"))
CHUNK_DAYS = int(os.environ.get("CHUNK_DAYS", "5"))
CHUNK_DELAY = float(os.environ.get("CHUNK_DELAY", "0.45"))
QUICK = os.environ.get("QUICK", "0") == "1"


def baseline_params() -> dict[str, Any]:
    from trading_shared.strategies.intraday_desk.intra_vwap_orb_tuning import INTRA_VWAP_ORB_LEGACY

    return dict(INTRA_VWAP_ORB_LEGACY)


def _coverage_ok(df, from_date: date, to_date: date) -> bool:
    if df is None or len(df) < 200:
        return False
    ts = df["timestamp"]
    try:
        import pandas as pd

        tmin = pd.to_datetime(ts.min(), errors="coerce")
        tmax = pd.to_datetime(ts.max(), errors="coerce")
        if tmin is None or tmax is None or pd.isna(tmin) or pd.isna(tmax):
            return False
        span = (tmax.date() - tmin.date()).days + 1
        requested = (to_date - from_date).days + 1
        return span >= int(requested * 0.55) and len(df) >= int(requested * 0.55 * 40)
    except Exception:
        return False


async def _fetch_angel_chunked(user_id: int, exchange: str, token: str, from_date: date, to_date: date):
    import pandas as pd
    import redis
    from trading_shared.broker.angel_one.client import AngelOneAPIError
    from trading_shared.broker.angel_one.schemas import CandleRequest
    from trading_shared.broker.angel_one.session_manager import AngelOneSessionManager
    from trading_shared.config import get_settings
    from trading_shared.db.session import SessionLocal

    rate_sleep = float(os.environ.get("RATE_LIMIT_SLEEP", "70"))
    max_retries = int(os.environ.get("CHUNK_RETRIES", "6"))
    settings = get_settings()
    db = SessionLocal()
    frames = []
    try:
        redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        manager = AngelOneSessionManager(db, redis_client)
        client = await manager.get_client_for_user(user_id)
        cur = from_date
        while cur <= to_date:
            chunk_end = min(cur + timedelta(days=CHUNK_DAYS - 1), to_date)
            rows = []
            last_err = None
            for attempt in range(max_retries):
                try:
                    response = await client.get_candles(
                        CandleRequest(
                            exchange=exchange,
                            symboltoken=token,
                            interval="FIVE_MINUTE",
                            fromdate=f"{cur.isoformat()} 09:15",
                            todate=f"{chunk_end.isoformat()} 15:30",
                        )
                    )
                    candles = response.get("data") or []
                    for row in candles:
                        if not isinstance(row, (list, tuple)) or len(row) < 6:
                            continue
                        rows.append(
                            {
                                "timestamp": pd.to_datetime(row[0]),
                                "open": float(row[1]),
                                "high": float(row[2]),
                                "low": float(row[3]),
                                "close": float(row[4]),
                                "volume": float(row[5]),
                            }
                        )
                    last_err = None
                    break
                except Exception as exc:
                    last_err = exc
                    msg = str(exc).lower()
                    if "rate limit" in msg or "access denied" in msg or getattr(exc, "status_code", None) in (403, 429):
                        print(
                            f"    rate-limit {cur}→{chunk_end} attempt {attempt + 1}/{max_retries}; sleep {rate_sleep}s",
                            flush=True,
                        )
                        await asyncio.sleep(rate_sleep)
                        continue
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2.0 * (attempt + 1))
                        continue
                    raise
            if last_err and not rows:
                raise last_err
            if rows:
                frames.append(pd.DataFrame(rows))
            cur = chunk_end + timedelta(days=1)
            if cur <= to_date:
                await asyncio.sleep(CHUNK_DELAY)
    finally:
        db.close()
    if not frames:
        return pd.DataFrame()
    merged = pd.concat(frames, ignore_index=True)
    merged["timestamp"] = pd.to_datetime(merged["timestamp"], errors="coerce")
    return (
        merged.dropna(subset=["timestamp"])
        .drop_duplicates(subset=["timestamp"])
        .sort_values("timestamp")
        .reset_index(drop=True)
    )


def load_frames():
    if os.path.isfile(CACHE) and os.environ.get("FORCE_RELOAD") != "1":
        with open(CACHE, "rb") as f:
            payload = pickle.load(f)
        print(f"Loaded cache {CACHE}: symbols={len(payload['frames'])} src={payload.get('source')}", flush=True)
        return payload

    from trading_shared.backtest.data_loader import BacktestDataLoader
    from trading_shared.db.session import SessionLocal
    from trading_shared.strategies.intraday_desk.stock_picker import default_universe

    user_id = int(os.environ.get("BACKTEST_USER_ID", "1"))
    days = int(os.environ.get("BACKTEST_DAYS", "180"))
    allow_db_fallback = os.environ.get("ALLOW_DB_FALLBACK", "1") == "1"
    use_db_only = os.environ.get("USE_DB_ONLY", "0") == "1"
    symbol_pause = float(os.environ.get("SYMBOL_PAUSE", "8"))
    to_date = date.today()
    from_date = to_date - timedelta(days=days)
    symbols = default_universe()
    if SYMBOL_LIMIT > 0:
        symbols = symbols[:SYMBOL_LIMIT]

    db = SessionLocal()
    frames = []
    sources = {}
    try:
        loader = BacktestDataLoader(db)
        for symbol in symbols:
            try:
                token, resolved = loader.resolve_token(symbol, None)
                db_df = loader._load_from_db(token, "5m", from_date.isoformat(), to_date.isoformat())
                src = "database"
                df = db_df
                if use_db_only:
                    if len(db_df) < 400:
                        print(f"  skip {resolved}: DB only {len(db_df)} bars", flush=True)
                        continue
                    src = "database"
                    df = db_df
                elif not _coverage_ok(db_df, from_date, to_date):
                    print(f"  {resolved}: DB sparse ({len(db_df)} bars) → Angel chunked…", flush=True)
                    try:
                        angel_df = asyncio.run(
                            _fetch_angel_chunked(user_id, "NSE", token, from_date, to_date)
                        )
                        if len(angel_df) > len(db_df):
                            df = angel_df
                            src = "angel_one"
                        elif allow_db_fallback and len(db_df) >= 400:
                            df = db_df
                            src = "database_sparse"
                            print(f"  {resolved}: Angel incomplete; using DB {len(db_df)} bars", flush=True)
                        else:
                            print(f"  skip {resolved}: insufficient data", flush=True)
                            continue
                    except Exception as exc:
                        if allow_db_fallback and len(db_df) >= 400:
                            df = db_df
                            src = "database_sparse"
                            print(f"  {resolved}: Angel failed ({exc}); using DB {len(db_df)} bars", flush=True)
                        else:
                            print(f"  skip {resolved}: {exc}", flush=True)
                            continue
                if len(df) >= 200:
                    frames.append((resolved, df))
                    sources[resolved] = src
                    print(f"  {resolved}: {len(df)} bars ({src})", flush=True)
                if (not use_db_only) and symbol_pause > 0:
                    time.sleep(symbol_pause)
            except Exception as exc:
                print(f"  skip {symbol}: {exc}", flush=True)
    finally:
        db.close()

    primary = "angel_one" if any(v == "angel_one" for v in sources.values()) else "database"
    payload = {
        "frames": frames,
        "source": primary,
        "sources": sources,
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
        if len(part) >= 80:
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
        risk_pct=float(params.get("risk_pct") or 1.0),
        top_n=max(len(picks), 1),
        params=params,
        symbol_frames=frames,
        picks=picks,
    )


def metrics(res):
    trades = res.get("trades") or []
    n = int(res.get("total_trades") or 0)
    pnl = float(res.get("total_pnl") or 0)
    wins = [t for t in trades if float(t.get("pnl") or 0) > 0]
    losses = [t for t in trades if float(t.get("pnl") or 0) <= 0]
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
    }


def score(m, ref_n=30):
    """Bias toward win rate + total profit while keeping PF/expectancy/DD in check."""
    n = m["trades"]
    wr = float(m["win_rate"])
    pf = min(float(m["profit_factor"] or 0), 5.0)
    exp = float(m["expectancy"] or 0)
    pnl = float(m["total_pnl"] or 0)
    dd = float(m["max_drawdown"] or 0)
    if n < MIN_TRADES:
        return -100.0 + n + wr * 0.08
    if exp <= 0 and pnl <= 0:
        return wr * 0.8 + pf - 30
    trade_sc = max(0.0, min(n / max(ref_n, 1), 2.5)) * 8
    return (
        wr * 3.0
        + pf * 10
        + max(min(exp / 60, 16), -10)
        + trade_sc
        + max(min(pnl / 2000, 18), -12)
        - min(dd / 2.0, 22)
    )


def main() -> int:
    t0 = time.time()
    payload = load_frames()
    frames = payload["frames"]
    if not frames:
        print("No frames loaded — connect Angel One and retry.", flush=True)
        return 1

    base = baseline_params()
    print(
        f"=== {STRATEGY_CODE} symbols={len(frames)} {payload['from_date']}→{payload['to_date']} "
        f"src={payload.get('source')} ===",
        flush=True,
    )

    from trading_shared.strategies.intraday_desk.backtest import run_intraday_strategy_backtest

    active = []
    for sym, df in frames:
        r = run_intraday_strategy_backtest(df, STRATEGY_CODE, sym, params=base)
        if int(r.get("total_trades") or 0) > 0:
            active.append((sym, df))
    use_frames = active if len(active) >= 5 else frames
    picks = [{"symbol": sym, "score": 1.0} for sym, _ in use_frames]
    print(f"Active symbols={len(use_frames)} / {len(frames)}", flush=True)
    print("Picks:", [p["symbol"] for p in picks], flush=True)

    print("\n--- BASELINE ---", flush=True)
    base_full = metrics(run_universe(use_frames, base, picks=picks))
    train = split_frames(use_frames, 0.0, 0.6)
    val = split_frames(use_frames, 0.6, 0.8)
    oos = split_frames(use_frames, 0.8, 1.0)
    base_train = metrics(run_universe(train, base, picks=picks))
    base_val = metrics(run_universe(val, base, picks=picks))
    base_oos = metrics(run_universe(oos, base, picks=picks))
    print(
        json.dumps({"full": base_full, "train": base_train, "val": base_val, "oos": base_oos}, indent=2),
        flush=True,
    )

    rows = []
    work = deepcopy(base)
    ref_n = max(base_train["trades"], 20)

    def ev(label, group, params, dataset="train"):
        data = {"train": train, "val": val, "oos": oos, "full": use_frames}[dataset]
        m = metrics(run_universe(data, params, picks=picks))
        sc = score(m, ref_n)
        row = {
            "label": label,
            "group": group,
            "dataset": dataset,
            "params": dict(params),
            "metrics": m,
            "score": round(sc, 2),
        }
        rows.append(row)
        print(
            f"{group:10} {label:28} [{dataset}] n={m['trades']:>4} WR={m['win_rate']:>6}% "
            f"PF={m['profit_factor']:>6} EXP={m['expectancy']:>8} PnL={m['total_pnl']:>10} "
            f"DD={m['max_drawdown']:>6} sc={sc:>6.1f}",
            flush=True,
        )
        return row

    def best(group):
        g = [r for r in rows if r["group"] == group and r["dataset"] == "train" and r["metrics"]["trades"] >= MIN_TRADES]
        pos = [r for r in g if r["metrics"]["total_pnl"] > 0 or r["metrics"]["expectancy"] > 0]
        pool = pos or g or [r for r in rows if r["group"] == group and r["dataset"] == "train"]
        if not pool:
            return None
        return max(pool, key=lambda r: (r["score"], r["metrics"]["win_rate"], r["metrics"]["total_pnl"]))

    def lock(group, *keys):
        b = best(group)
        if not b:
            return
        for k in keys:
            if k in b["params"]:
                work[k] = b["params"][k]
        print("LOCK", group, {k: work.get(k) for k in keys}, flush=True)

    vol_grid = [1.1, 1.2, 1.3, 1.5, 1.75, 2.0, 2.25] if not QUICK else [1.3, 1.5, 1.75]
    atr_grid = [1.0, 1.25, 1.5, 1.75, 2.0] if not QUICK else [1.25, 1.5, 1.75]
    scale_grid = [1.0, 1.25, 1.5, 2.0, 2.5] if not QUICK else [1.25, 1.5, 2.0]
    ema_pairs = [(5, 13), (8, 21), (9, 21), (9, 34), (13, 34)] if not QUICK else [(8, 21), (9, 21), (9, 34)]

    print("\n--- Volume ---", flush=True)
    for v in vol_grid:
        p = deepcopy(work)
        p["vol_mult"] = v
        ev(f"vol_{v}", "vol", p)
    lock("vol", "vol_mult")
    for lb in ([8, 10, 15, 20, 30] if not QUICK else [10, 15, 20]):
        p = deepcopy(work)
        p["vol_lookback"] = lb
        ev(f"vlb_{lb}", "vlook", p)
    lock("vlook", "vol_lookback")

    print("\n--- OR / entry window ---", flush=True)
    for or_mins in ([15, 20, 30, 45] if not QUICK else [15, 30]):
        p = deepcopy(work)
        p["or_end_min"] = 9 * 60 + 15 + or_mins
        if int(p["entry_start_min"]) < int(p["or_end_min"]):
            p["entry_start_min"] = int(p["or_end_min"])
        ev(f"or_{or_mins}m", "or", p)
    lock("or", "or_end_min", "entry_start_min")
    for start in ([9 * 60 + 20, 9 * 60 + 30, 9 * 60 + 45, 10 * 60] if not QUICK else [9 * 60 + 30, 9 * 60 + 45]):
        if start < int(work["or_end_min"]):
            continue
        p = deepcopy(work)
        p["entry_start_min"] = start
        ev(f"start_{start}", "start", p)
    lock("start", "entry_start_min")
    for end in ([12 * 60, 13 * 60, 14 * 60, 14 * 60 + 45] if not QUICK else [13 * 60, 14 * 60 + 45]):
        p = deepcopy(work)
        p["entry_end_min"] = end
        ev(f"end_{end}", "end", p)
    lock("end", "entry_end_min")

    print("\n--- EMA trend ---", flush=True)
    for fast, slow in ema_pairs:
        p = deepcopy(work)
        p["ema_fast"] = fast
        p["ema_slow"] = slow
        ev(f"ema_{fast}_{slow}", "ema", p)
    lock("ema", "ema_fast", "ema_slow")

    print("\n--- Stops / targets ---", flush=True)
    for am in atr_grid:
        p = deepcopy(work)
        p["atr_stop_mult"] = am
        ev(f"atr_stop_{am}", "stop", p)
    lock("stop", "atr_stop_mult")
    for be in ([0.5, 0.75, 1.0, 1.25, 1.5] if not QUICK else [0.75, 1.0, 1.25]):
        p = deepcopy(work)
        p["breakeven_atr_mult"] = be
        ev(f"be_{be}", "be", p)
    lock("be", "breakeven_atr_mult")
    for sr in scale_grid:
        p = deepcopy(work)
        p["scale_out_r"] = sr
        ev(f"scale_{sr}", "scale", p)
    lock("scale", "scale_out_r")

    print("\n--- Side / risk / day caps ---", flush=True)
    for lo in [False, True]:
        p = deepcopy(work)
        p["long_only"] = lo
        ev(f"long_only_{lo}", "side", p)
    lock("side", "long_only")
    for mt in ([1, 2, 3] if not QUICK else [1, 2]):
        p = deepcopy(work)
        p["max_trades_per_day"] = mt
        ev(f"maxtr_{mt}", "maxtr", p)
    lock("maxtr", "max_trades_per_day")
    for cs in ([1, 2, 3] if not QUICK else [2, 3]):
        p = deepcopy(work)
        p["max_consec_stops"] = cs
        ev(f"chop_{cs}", "chop", p)
    lock("chop", "max_consec_stops")
    for rp in ([0.75, 1.0, 1.25] if not QUICK else [1.0]):
        p = deepcopy(work)
        p["risk_pct"] = rp
        ev(f"risk_{rp}", "risk", p)
    lock("risk", "risk_pct")

    print("\n--- Combos / WF ---", flush=True)
    combos = [deepcopy(base), deepcopy(work)]
    for d_vol, d_atr, d_scale in [(-0.2, 0.0, 0.0), (0.25, 0.0, 0.0), (0.0, 0.25, 0.0), (0.0, 0.0, 0.25), (0.2, 0.25, -0.25)]:
        p = deepcopy(work)
        p["vol_mult"] = max(1.0, float(p["vol_mult"]) + d_vol)
        p["atr_stop_mult"] = max(0.75, float(p["atr_stop_mult"]) + d_atr)
        p["scale_out_r"] = max(1.0, float(p["scale_out_r"]) + d_scale)
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
        [r for r in combo_train if r["metrics"]["trades"] >= MIN_TRADES and (r["metrics"]["expectancy"] > 0 or r["metrics"]["total_pnl"] > 0)],
        key=lambda r: r["score"],
        reverse=True,
    )[:8] or sorted(combo_train, key=lambda r: r["score"], reverse=True)[:5]

    val_rows = []
    for tr in top:
        vr = ev(tr["label"] + "_val", "combo_val", tr["params"], dataset="val")
        val_rows.append({**vr, "train_score": tr["score"]})

    recommended = None
    if val_rows:
        # Prefer positive val PnL, then better WR vs baseline, then score.
        recommended = sorted(
            val_rows,
            key=lambda r: (
                1 if r["metrics"]["total_pnl"] > 0 else 0,
                1 if r["metrics"]["profit_factor"] >= 1.0 else 0,
                1 if r["metrics"]["win_rate"] >= base_train["win_rate"] else 0,
                r["score"],
                r["metrics"]["win_rate"],
                r["metrics"]["total_pnl"],
                r.get("train_score", 0),
            ),
            reverse=True,
        )[0]

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
            "OFAT locked on train; recommended chosen on validation (WR + PnL bias).",
            "OOS not used for parameter selection.",
            "Angel One 5m chunked load when DB coverage is sparse.",
        ],
    }
    out = os.environ.get("REPORT_PATH", "/tmp/optimize_intra_vwap_orb_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote {out} elapsed={report['elapsed_sec']}s", flush=True)
    print("\n=== TOP 10 TRAIN ===", flush=True)
    for i, r in enumerate(ranked_rows[:10], 1):
        m = r["metrics"]
        print(
            f"{i:2}. [{r['group']}] {r['label']} sc={r['score']} WR={m['win_rate']}% "
            f"PF={m['profit_factor']} EXP={m['expectancy']} tr={m['trades']} PnL={m['total_pnl']}",
            flush=True,
        )
    if recommended:
        print("\n=== RECOMMENDED ===", flush=True)
        print(
            json.dumps(
                {
                    "params": recommended["params"],
                    "val": recommended["metrics"],
                    "oos": (rec_oos or {}).get("metrics"),
                    "full": (rec_full or {}).get("metrics"),
                    "baseline_full": base_full,
                },
                indent=2,
                default=str,
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
