#!/usr/bin/env python3
"""SCALP-AD-005 (Momentum Burst) optimization — Bank Nifty.

Note: Current defaults produce ~0 trades on 60d Angel One 1m Bank Nifty data
(VWAP distance 0.35% + Supertrend + 2-bar momentum + volume). Entry filters are
swept first so ATR risk can be optimized on a tradeable configuration.

    PYTHONUNBUFFERED=1 python /app/scripts/optimize_scalp_ad005.py
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

STRATEGY_CODE = "SCALP-AD-005"
INSTRUMENT_KEY = "banknifty"
BACKTEST_DAYS = int(os.environ.get("BACKTEST_DAYS", "60"))
SAMPLE_BARS = int(os.environ.get("SAMPLE_BARS", "25000"))
MIN_TRADES = int(os.environ.get("MIN_TRADES", "8"))
CANDLE_CACHE = os.environ.get("CANDLE_CACHE", "/tmp/ad005_candles.pkl")

_P: dict[str, Any] = {}
_EMA_FAST = 9
_EMA_SLOW = 21
_SESSION = "both"
_ST_PERIOD = 10
_ST_MULT = 3.0


def baseline_params() -> dict[str, Any]:
    return {
        "mb_ema_fast": 9,
        "mb_ema_slow": 21,
        "mb_ema_sep_pct": 0.04,
        "mb_rsi_call_min": 46,
        "mb_rsi_call_max": 62,
        "mb_rsi_put_min": 40,
        "mb_rsi_put_max": 52,
        "mb_vwap_distance_pct": 0.35,
        "mb_require_vwap": True,
        "mb_index_volume_spike_ratio": 1.12,
        "mb_volume_spike_ratio": 1.35,
        "mb_require_supertrend": True,
        "mb_st_period": 10,
        "mb_st_mult": 3.0,
        "mb_stop_atr_mult": 1.20,
        "mb_stop_floor_pct": 0.0002,
        "mb_target_atr_mult": 0.50,
        "mb_min_target_pts": 10.0,
        "mb_max_hold_bars": 8,
        "mb_require_rsi_slope": False,
        "mb_momentum_mode": "a",
        "mb_momentum_atr": 0.0,
        "mb_ema_mode": "or",
        "mb_require_two_bar_momentum": True,
    }


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
        df, source, notes = await svc._load_desk_backtest_candles(from_date, to_date.isoformat(), "1m")
        if notes:
            print("notes:", "; ".join(notes), flush=True)
        if len(df) > SAMPLE_BARS:
            df = df.tail(SAMPLE_BARS).reset_index(drop=True)
        return df, source, from_date, to_date.isoformat()
    finally:
        db.close()


def get_candles(user_id: int):
    for path in (CANDLE_CACHE, "/tmp/bt003_candles.pkl", "/tmp/bt002_candles.pkl"):
        if os.path.isfile(path) and os.environ.get("FORCE_RELOAD") != "1":
            with open(path, "rb") as f:
                payload = pickle.load(f)
            print(f"Loaded cache {path}: bars={len(payload['df']):,}", flush=True)
            if path != CANDLE_CACHE:
                with open(CANDLE_CACHE, "wb") as f:
                    pickle.dump(payload, f)
            return payload["df"], payload["source"], payload["from_date"], payload["to_date"]
    df, source, from_date, to_date = asyncio.run(load_candles(user_id))
    with open(CANDLE_CACHE, "wb") as f:
        pickle.dump({"df": df, "source": source, "from_date": from_date, "to_date": to_date}, f)
    return df, source, from_date, to_date


def install_patches() -> None:
    import trading_shared.strategies.scalping_desk.backtest as bt
    import trading_shared.strategies.scalping_desk.battle_tested_scalp as bts
    import trading_shared.strategies.scalping_desk.engine as eng
    import trading_shared.strategies.scalping_desk.strategies as strat
    from trading_shared.strategies.scalping_desk.strategies import (
        _build_signal,
        _ema_separated,
        _two_bar_momentum,
    )
    from trading_shared.strategies.ta import ema, supertrend

    _orig_enrich = eng.enrich_candles
    _orig_window = bts._active_battle_window
    _orig_risk = eng.compute_scalp_risk
    _orig_hold = eng.max_hold_bars

    def enrich_patched(df):
        out = _orig_enrich(df).copy()
        if _EMA_FAST != 9 or _EMA_SLOW != 21:
            out["ema9"] = ema(out["close"], _EMA_FAST)
            out["ema21"] = ema(out["close"], _EMA_SLOW)
        if _ST_PERIOD != 10 or abs(_ST_MULT - 3.0) > 1e-9:
            out["supertrend_dir"] = supertrend(out, period=_ST_PERIOD, multiplier=_ST_MULT)
        return out

    def window_patched(ts):
        label = _orig_window(ts)
        if _SESSION == "both":
            return label
        if label is None:
            return None
        if _SESSION == "morning" and str(label).startswith("09:20"):
            return label
        if _SESSION == "afternoon" and str(label).startswith("13:30"):
            return label
        return None

    def risk_patched(spot, atr, instrument_key="nifty50"):
        if instrument_key == "banknifty" and _P:
            stop = max(float(atr) * float(_P["mb_stop_atr_mult"]), float(spot) * float(_P["mb_stop_floor_pct"]))
            tgt = max(float(atr) * float(_P["mb_target_atr_mult"]), float(_P["mb_min_target_pts"]))
            return round(stop, 2), round(tgt, 2)
        return _orig_risk(spot, atr, instrument_key)

    def hold_patched(instrument_key):
        if instrument_key == "banknifty" and _P:
            return int(_P["mb_max_hold_bars"])
        return _orig_hold(instrument_key)

    def momentum_ok(data, direction: str) -> bool:
        mode = str(_P.get("mb_momentum_mode") or "a")
        if not _P.get("mb_require_two_bar_momentum", True) or mode == "off":
            return True
        if mode == "a":
            return _two_bar_momentum(data, direction)
        if len(data) < 3:
            return False
        c2, c3 = data.iloc[-2], data.iloc[-1]
        if mode == "b":
            return (float(c3["close"]) > float(c2["close"])) if direction == "CALL" else (float(c3["close"]) < float(c2["close"]))
        atr = float(c3.get("atr") or 0) or max(float(c3["close"]) * 0.001, 1.0)
        if abs(float(c3["close"]) - float(c2["open"])) < atr * float(_P.get("mb_momentum_atr") or 0):
            return False
        return _two_bar_momentum(data, direction)

    def ema_dir_ok(data, direction: str) -> bool:
        mode = str(_P.get("mb_ema_mode") or "or")
        row = data.iloc[-1]
        if direction == "CALL":
            cross = False
            if len(data) >= 4:
                tail = data.tail(4)
                cross = any(
                    tail["ema9"].iloc[i] > tail["ema21"].iloc[i]
                    and tail["ema9"].iloc[i - 1] <= tail["ema21"].iloc[i - 1]
                    for i in range(1, len(tail))
                )
            direction_ok = float(row["ema9"]) > float(row["ema21"])
        else:
            cross = False
            if len(data) >= 4:
                tail = data.tail(4)
                cross = any(
                    tail["ema9"].iloc[i] < tail["ema21"].iloc[i]
                    and tail["ema9"].iloc[i - 1] >= tail["ema21"].iloc[i - 1]
                    for i in range(1, len(tail))
                )
            direction_ok = float(row["ema9"]) < float(row["ema21"])
        if mode == "cross":
            return cross
        if mode == "direction":
            return direction_ok
        return cross or direction_ok

    def evaluate_patched(df, timeframe, option_chain, lot_size, *, enriched=False, instrument_key="nifty50", params=None, skip_session=False):
        if len(df) < 21:
            return None
        p = {**baseline_params(), **(_P or {})}
        if isinstance((params or {}).get("momentum_burst"), dict):
            p.update(params["momentum_burst"])
        data = df if enriched else enrich_patched(df)
        row = data.iloc[-1]
        ts = row.get("timestamp")
        if not skip_session and not bts.in_battle_session(ts, df=data, instrument_key=instrument_key):
            return None

        spot = float(row["close"])
        rsi_val = float(row["rsi14"])
        st_dir = float(row["supertrend_dir"] or 0)
        vol_ratio = float(row["volume_ratio"])
        vwap = float(row["vwap"])
        vol_min = float(p["mb_index_volume_spike_ratio"])
        if not (bool(row.get("volume_proxy")) or instrument_key in ("nifty50", "banknifty")):
            vol_min = float(p["mb_volume_spike_ratio"])
        vol_ok = vol_ratio >= vol_min or bool(row.get("vol_spike"))

        sep = float(p["mb_ema_sep_pct"])
        if sep > 0 and not _ema_separated(data, spot, min_pct=sep):
            return None

        require_vwap = bool(p["mb_require_vwap"])
        dist_pct = float(p["mb_vwap_distance_pct"])
        dist = abs(spot - vwap) / max(spot, 1) * 100
        dist_ok = True if dist_pct <= 0 else dist <= dist_pct
        require_st = bool(p["mb_require_supertrend"])
        require_slope = bool(p.get("mb_require_rsi_slope"))
        prev_rsi = float(data.iloc[-2]["rsi14"]) if len(data) >= 2 else rsi_val

        call_ok = (
            ema_dir_ok(data, "CALL")
            and float(p["mb_rsi_call_min"]) <= rsi_val <= float(p["mb_rsi_call_max"])
            and (not require_vwap or spot > vwap)
            and dist_ok
            and (not require_st or st_dir > 0)
            and vol_ok
            and momentum_ok(data, "CALL")
            and (not require_slope or rsi_val > prev_rsi)
        )
        put_ok = (
            ema_dir_ok(data, "PUT")
            and float(p["mb_rsi_put_min"]) <= rsi_val <= float(p["mb_rsi_put_max"])
            and (not require_vwap or spot < vwap)
            and dist_ok
            and (not require_st or st_dir < 0)
            and vol_ok
            and momentum_ok(data, "PUT")
            and (not require_slope or rsi_val < prev_rsi)
        )
        if not call_ok and not put_ok:
            return None
        return _build_signal(
            strategy_id="momentum_burst",
            strategy_label="Momentum Burst",
            signal_type="CALL" if call_ok else "PUT",
            data=data,
            timeframe=timeframe,
            option_chain=option_chain,
            instrument_key=instrument_key,
            conditions=["momentum_burst"],
            hold_bars=int(p["mb_max_hold_bars"]),
        )

    eng.enrich_candles = enrich_patched
    bt.enrich_candles = enrich_patched
    bts._active_battle_window = window_patched
    eng.compute_scalp_risk = risk_patched
    strat.compute_scalp_risk = risk_patched
    eng.max_hold_bars = hold_patched
    strat.max_hold_bars = hold_patched
    strat.evaluate_momentum_burst = evaluate_patched
    strat.STRATEGY_REGISTRY["momentum_burst"]["evaluate"] = evaluate_patched


def set_cfg(params: dict[str, Any], *, session: str = "both") -> None:
    global _P, _EMA_FAST, _EMA_SLOW, _SESSION, _ST_PERIOD, _ST_MULT
    _P = dict(params)
    _EMA_FAST = int(params.get("mb_ema_fast", 9))
    _EMA_SLOW = int(params.get("mb_ema_slow", 21))
    _SESSION = session
    _ST_PERIOD = int(params.get("mb_st_period", 10))
    _ST_MULT = float(params.get("mb_st_mult", 3.0))


def run_bt(candles, lot: int, capital: float) -> dict[str, Any]:
    from trading_shared.strategies.scalping_desk.backtest import run_backtest

    return run_backtest(
        candles,
        "1m",
        lot,
        capital,
        strategy_code=STRATEGY_CODE,
        instrument_key=INSTRUMENT_KEY,
        params={"momentum_burst": dict(_P)},
        max_loss_per_day=5000,
        max_trades_per_day=5,
        ai_entry=False,
        ai_exit=False,
    )


def _hhmm(ts: str) -> int | None:
    try:
        part = ts.split("T")[1][:5] if "T" in ts else ts.split(" ")[1][:5]
        hh, mm = part.split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        return None


def streak_stats(trades):
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
    return {"max_consec_wins": max_w, "max_consec_losses": max_l}


def metrics(result: dict[str, Any], candles=None) -> dict[str, Any]:
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
    morning, afternoon = [], []
    for t in trades:
        hhmm = _hhmm(str(t.get("entry_time") or ""))
        if hhmm is None:
            continue
        if 9 * 60 + 20 <= hhmm <= 10 * 60 + 30:
            morning.append(t)
        elif 13 * 60 + 30 <= hhmm <= 14 * 60 + 45:
            afternoon.append(t)

    regimes: dict[str, list] = {}
    if candles is not None and len(trades) and "timestamp" in candles.columns:
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
    regime_stats = {
        k: {
            "wr": subset(rows)[0],
            "n": subset(rows)[1],
            "pnl": round(sum(float(x.get("pnl") or 0) for x in rows), 2),
        }
        for k, rows in regimes.items()
    }
    cw, cn = subset(calls)
    pw, pn = subset(puts)
    mw, mn = subset(morning)
    aw, an = subset(afternoon)
    return {
        "trades": n,
        "win_rate": wr,
        "wins": wins,
        "losses": n - wins,
        "profit_factor": pf,
        "expectancy": expectancy,
        "total_pnl": pnl,
        "max_drawdown": dd,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "call_wr": cw,
        "call_n": cn,
        "put_wr": pw,
        "put_n": pn,
        "morning_wr": mw,
        "morning_n": mn,
        "afternoon_wr": aw,
        "afternoon_n": an,
        "regimes": regime_stats,
        **streak_stats(trades),
    }


def balanced_score(m: dict[str, Any], baseline_trades: int) -> float:
    trades = m["trades"]
    if trades < MIN_TRADES:
        return -100.0 + trades
    wr = float(m["win_rate"])
    pf = min(float(m["profit_factor"] or 0), 3.0)
    exp = float(m["expectancy"] or 0)
    dd = float(m["max_drawdown"] or 0)
    pnl = float(m["total_pnl"] or 0)
    trade_ratio = trades / max(baseline_trades, 1)
    trade_score = max(0.0, min(trade_ratio, 2.5)) * 12.0
    if trade_ratio < 0.5:
        trade_score -= 15.0
    return (
        wr * 1.8
        + pf * 18.0
        + max(min(exp / 200.0, 20.0), -20.0)
        + trade_score
        + max(min(pnl / 5000.0, 15.0), -15.0)
        - min(dd / 1000.0, 40.0)
    )


def split_wf(candles):
    n = len(candles)
    i1, i2 = int(n * 0.60), int(n * 0.80)
    return (
        candles.iloc[:i1].reset_index(drop=True),
        candles.iloc[i1:i2].reset_index(drop=True),
        candles.iloc[i2:].reset_index(drop=True),
    )


def main() -> int:
    import trading_shared.strategies.scalping_desk.backtest as bt
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

    bt.MAX_BACKTEST_BARS = int(os.environ.get("MAX_BACKTEST_BARS", "30000"))
    install_patches()
    user_id = int(os.environ.get("BACKTEST_USER_ID", "1"))
    capital = float(os.environ.get("BACKTEST_CAPITAL", "100000"))
    lot = int(INSTRUMENTS[INSTRUMENT_KEY]["lot_size"])

    print(f"=== Optimize {STRATEGY_CODE} · {BACKTEST_DAYS}d ===", flush=True)
    candles, source, from_date, to_date = get_candles(user_id)
    print(f"bars={len(candles):,} source={source} {from_date}→{to_date}", flush=True)
    train, val, oos = split_wf(candles)
    print(f"WF train={len(train)} val={len(val)} oos={len(oos)}", flush=True)

    base = baseline_params()
    set_cfg(base)
    print("\n--- BASELINE (unchanged defaults) ---", flush=True)
    base_full = metrics(run_bt(candles, lot, capital), candles)
    base_train = metrics(run_bt(train, lot, capital), train)
    print(json.dumps({"full": base_full, "train": base_train}, indent=2), flush=True)
    if base_full["trades"] == 0:
        print(
            "NOTE: Current defaults produce 0 trades on this dataset. "
            "Entry filters will be optimized before ATR risk.",
            flush=True,
        )

    rows: list[dict[str, Any]] = []

    def evaluate(label: str, group: str, params: dict[str, Any], *, dataset="train", session="both") -> dict[str, Any]:
        set_cfg(params, session=session)
        data = {"train": train, "val": val, "oos": oos, "full": candles}[dataset]
        m = metrics(run_bt(data, lot, capital), data if dataset != "full" else candles)
        # Use max(base trades, 15) so zero-trade baseline does not over-reward trade spam
        ref = max(base_train["trades"], 15) if dataset == "train" else max(base_full["trades"], 15)
        sc = balanced_score(m, ref)
        row = {"label": label, "group": group, "dataset": dataset, "params": deepcopy(params), "metrics": m, "score": round(sc, 2), "session": session}
        rows.append(row)
        print(
            f"{group:12} {label:30} [{dataset}] tr={m['trades']:>3} WR={m['win_rate']:>5}% "
            f"PF={m['profit_factor']:>5} EXP={m['expectancy']:>8} PnL={m['total_pnl']:>9} DD={m['max_drawdown']:>8} sc={sc:>6.1f}",
            flush=True,
        )
        return row

    def best(group: str):
        g = [r for r in rows if r["group"] == group and r["dataset"] == "train" and r["metrics"]["trades"] >= MIN_TRADES]
        if not g:
            g = [r for r in rows if r["group"] == group and r["dataset"] == "train" and r["metrics"]["trades"] >= 3]
        return max(g, key=lambda r: r["score"]) if g else None

    # --- Entry viability (required because baseline has 0 trades) ---
    print("\n--- ENTRY: VWAP distance ---", flush=True)
    for d in [0.0, 0.35, 0.50, 0.75, 1.0, 1.25, 1.5, 2.0]:
        p = deepcopy(base)
        p["mb_vwap_distance_pct"] = d
        evaluate(f"vwap_dist_{d}", "vwap_dist", p)

    print("\n--- ENTRY: Supertrend ON/OFF ---", flush=True)
    for flag in (True, False):
        p = deepcopy(base)
        p["mb_require_supertrend"] = flag
        p["mb_vwap_distance_pct"] = 1.0  # need some distance to get trades
        evaluate(f"st_{flag}", "st_req", p)

    print("\n--- ENTRY: Momentum ---", flush=True)
    for mode in ("a", "b", "off"):
        p = deepcopy(base)
        p["mb_vwap_distance_pct"] = 1.0
        p["mb_require_supertrend"] = False
        p["mb_momentum_mode"] = mode
        p["mb_require_two_bar_momentum"] = mode != "off"
        evaluate(f"mom_{mode}", "momentum", p)

    print("\n--- ENTRY: Volume ---", flush=True)
    for v in [1.0, 1.05, 1.08, 1.10, 1.12, 1.15, 1.20, 1.25, 1.30, 1.35]:
        p = deepcopy(base)
        p["mb_vwap_distance_pct"] = 1.0
        p["mb_require_supertrend"] = False
        p["mb_require_two_bar_momentum"] = False
        p["mb_momentum_mode"] = "off"
        p["mb_index_volume_spike_ratio"] = v
        evaluate(f"vol_{v}", "idx_vol", p)

    print("\n--- ENTRY: EMA sep ---", flush=True)
    for sep in [0.0, 0.02, 0.03, 0.04, 0.06, 0.08, 0.10]:
        p = deepcopy(base)
        p["mb_vwap_distance_pct"] = 1.0
        p["mb_require_supertrend"] = False
        p["mb_require_two_bar_momentum"] = False
        p["mb_momentum_mode"] = "off"
        p["mb_ema_sep_pct"] = sep
        evaluate(f"sep_{sep}", "ema_sep", p)

    # Build viable entry core from best OFAT pieces that produce trades
    print("\n--- ENTRY core assembly ---", flush=True)
    entry = deepcopy(base)
    # Diagnosis-driven defaults for tradeability on this dataset
    entry["mb_vwap_distance_pct"] = 1.0
    entry["mb_require_supertrend"] = False
    entry["mb_require_two_bar_momentum"] = False
    entry["mb_momentum_mode"] = "off"
    # Prefer OFAT winners when they beat and keep trades
    for group, key in [
        ("vwap_dist", "mb_vwap_distance_pct"),
        ("idx_vol", "mb_index_volume_spike_ratio"),
        ("ema_sep", "mb_ema_sep_pct"),
    ]:
        r = best(group)
        if r and r["metrics"]["trades"] >= MIN_TRADES:
            entry[key] = r["params"][key]
    r = best("st_req")
    if r and r["metrics"]["trades"] >= 3:
        entry["mb_require_supertrend"] = r["params"]["mb_require_supertrend"]
    r = best("momentum")
    if r and r["metrics"]["trades"] >= MIN_TRADES:
        entry["mb_momentum_mode"] = r["params"]["mb_momentum_mode"]
        entry["mb_require_two_bar_momentum"] = r["params"]["mb_require_two_bar_momentum"]

    # Candidate entry packs
    entry_packs = [
        ("entry_diag", entry),
        (
            "entry_strictish",
            {
                **deepcopy(base),
                "mb_vwap_distance_pct": 1.0,
                "mb_require_supertrend": True,
                "mb_require_two_bar_momentum": False,
                "mb_momentum_mode": "off",
                "mb_index_volume_spike_ratio": 1.10,
            },
        ),
        (
            "entry_mom_b",
            {
                **deepcopy(base),
                "mb_vwap_distance_pct": 1.0,
                "mb_require_supertrend": False,
                "mb_require_two_bar_momentum": True,
                "mb_momentum_mode": "b",
            },
        ),
        (
            "entry_vwap075_nomom",
            {
                **deepcopy(base),
                "mb_vwap_distance_pct": 0.75,
                "mb_require_supertrend": False,
                "mb_require_two_bar_momentum": False,
                "mb_momentum_mode": "off",
            },
        ),
    ]
    entry_rows = []
    for name, p in entry_packs:
        entry_rows.append(evaluate(name, "entry_pack", p))
    viable = [r for r in entry_rows if r["metrics"]["trades"] >= MIN_TRADES]
    if not viable:
        viable = sorted(entry_rows, key=lambda r: r["metrics"]["trades"], reverse=True)
    entry_best = max(viable, key=lambda r: r["score"])
    print(f"Selected entry pack: {entry_best['label']} trades={entry_best['metrics']['trades']} WR={entry_best['metrics']['win_rate']}", flush=True)
    work = deepcopy(entry_best["params"])
    entry_ref_trades = max(entry_best["metrics"]["trades"], 1)

    # --- Risk OFAT on viable entry ---
    print("\n--- RISK: ATR Target ---", flush=True)
    for t in [0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00, 1.10, 1.20, 1.50]:
        p = deepcopy(work)
        p["mb_target_atr_mult"] = t
        evaluate(f"tgt_{t}", "target_atr", p)
    print("\n--- RISK: Target floor ---", flush=True)
    for f in [5, 8, 10, 12, 15, 20]:
        p = deepcopy(work)
        p["mb_min_target_pts"] = float(f)
        evaluate(f"tgt_floor_{f}", "target_floor", p)
    print("\n--- RISK: ATR Stop ---", flush=True)
    for s in [0.60, 0.80, 1.00, 1.10, 1.20, 1.30, 1.40, 1.50, 1.75, 2.00]:
        p = deepcopy(work)
        p["mb_stop_atr_mult"] = s
        evaluate(f"sl_{s}", "stop_atr", p)
    print("\n--- RISK: Stop floor ---", flush=True)
    for f in [0.0001, 0.00015, 0.0002, 0.00025, 0.0003]:
        p = deepcopy(work)
        p["mb_stop_floor_pct"] = f
        evaluate(f"sl_floor_{f}", "stop_floor", p)

    sl_c = sorted([r for r in rows if r["group"] == "stop_atr" and r["metrics"]["trades"] >= 5], key=lambda r: r["score"], reverse=True)[:4]
    tg_c = sorted([r for r in rows if r["group"] == "target_atr" and r["metrics"]["trades"] >= 5], key=lambda r: r["score"], reverse=True)[:4]
    print("\n--- RISK: SL/Target combos ---", flush=True)
    for a, b in product(sl_c, tg_c):
        p = deepcopy(work)
        p["mb_stop_atr_mult"] = a["params"]["mb_stop_atr_mult"]
        p["mb_target_atr_mult"] = b["params"]["mb_target_atr_mult"]
        evaluate(f"rr_{p['mb_stop_atr_mult']}_{p['mb_target_atr_mult']}", "rr", p)

    print("\n--- RISK: Max hold ---", flush=True)
    for h in [3, 4, 5, 6, 7, 8, 10, 12, 15]:
        p = deepcopy(work)
        p["mb_max_hold_bars"] = h
        evaluate(f"hold_{h}", "hold", p)

    # Secondary filters on work base
    print("\n--- FILTER: RSI ---", flush=True)
    for lo, hi in [(44, 60), (46, 60), (46, 62), (48, 62), (50, 64), (52, 66)]:
        p = deepcopy(work)
        p.update({"mb_rsi_call_min": lo, "mb_rsi_call_max": hi})
        evaluate(f"call_{lo}_{hi}", "call_rsi", p)
    for lo, hi in [(38, 50), (40, 50), (40, 52), (42, 52), (42, 54), (38, 52)]:
        p = deepcopy(work)
        p.update({"mb_rsi_put_min": lo, "mb_rsi_put_max": hi})
        evaluate(f"put_{lo}_{hi}", "put_rsi", p)

    print("\n--- FILTER: EMA pairs ---", flush=True)
    for f, s in [(9, 21), (8, 21), (9, 20), (8, 20), (7, 18), (10, 21), (10, 24)]:
        p = deepcopy(work)
        p["mb_ema_fast"] = f
        p["mb_ema_slow"] = s
        evaluate(f"ema_{f}_{s}", "ema", p)

    print("\n--- FILTER: VWAP req / ST params / EMA mode / session ---", flush=True)
    for flag in (True, False):
        p = deepcopy(work)
        p["mb_require_vwap"] = flag
        evaluate(f"vwap_req_{flag}", "vwap_req", p)
    for flag in (False, True):
        p = deepcopy(work)
        p["mb_require_rsi_slope"] = flag
        evaluate(f"slope_{flag}", "rsi_slope", p)
    for per, mul in [(10, 3.0), (10, 2.5), (12, 3.0), (14, 3.0)]:
        p = deepcopy(work)
        p["mb_require_supertrend"] = True
        p["mb_st_period"] = per
        p["mb_st_mult"] = mul
        evaluate(f"st_{per}_{mul}", "st_params", p)
    for mode in ("or", "cross", "direction"):
        p = deepcopy(work)
        p["mb_ema_mode"] = mode
        evaluate(f"ema_mode_{mode}", "ema_mode", p)
    for sess in ("both", "morning", "afternoon"):
        evaluate(f"sess_{sess}", "session", deepcopy(work), session=sess)

    picks = {g: best(g) for g in [
        "vwap_dist", "st_req", "momentum", "idx_vol", "ema_sep", "entry_pack",
        "target_atr", "target_floor", "stop_atr", "stop_floor", "rr", "hold",
        "call_rsi", "put_rsi", "ema", "vwap_req", "rsi_slope", "st_params", "ema_mode", "session",
    ]}
    print("\n--- Best OFAT ---", flush=True)
    for g, r in picks.items():
        if r:
            print(f"  {g}: {r['label']} sc={r['score']} WR={r['metrics']['win_rate']} tr={r['metrics']['trades']}", flush=True)

    # Refined recommendation candidate
    rec = deepcopy(work)
    for group, keys in [
        ("rr", ["mb_stop_atr_mult", "mb_target_atr_mult"]),
        ("target_atr", ["mb_target_atr_mult"]),
        ("stop_atr", ["mb_stop_atr_mult"]),
        ("target_floor", ["mb_min_target_pts"]),
        ("stop_floor", ["mb_stop_floor_pct"]),
        ("hold", ["mb_max_hold_bars"]),
        ("call_rsi", ["mb_rsi_call_min", "mb_rsi_call_max"]),
        ("put_rsi", ["mb_rsi_put_min", "mb_rsi_put_max"]),
        ("ema", ["mb_ema_fast", "mb_ema_slow"]),
        ("ema_sep", ["mb_ema_sep_pct"]),
        ("idx_vol", ["mb_index_volume_spike_ratio"]),
        ("vwap_dist", ["mb_vwap_distance_pct"]),
        ("vwap_req", ["mb_require_vwap"]),
        ("ema_mode", ["mb_ema_mode"]),
    ]:
        r = picks.get(group)
        if r and r["score"] >= entry_best["score"] - 5 and r["metrics"]["trades"] >= max(MIN_TRADES // 2, 3):
            for k in keys:
                if k in r["params"]:
                    rec[k] = r["params"][k]

    print("\n--- Refined combos + stability ---", flush=True)
    combos = [deepcopy(work), deepcopy(rec), deepcopy(base)]
    # neighbours on ATR
    for d_sl, d_tg in product([-0.2, 0.0, 0.2], [-0.1, 0.0, 0.1]):
        p = deepcopy(rec)
        p["mb_stop_atr_mult"] = max(0.6, round(float(rec["mb_stop_atr_mult"]) + d_sl, 2))
        p["mb_target_atr_mult"] = max(0.4, round(float(rec["mb_target_atr_mult"]) + d_tg, 2))
        combos.append(p)
    # keep ST off vs on with rec
    p = deepcopy(rec)
    p["mb_require_supertrend"] = True
    combos.append(p)
    p = deepcopy(rec)
    p["mb_require_two_bar_momentum"] = True
    p["mb_momentum_mode"] = "b"
    combos.append(p)

    seen = set()
    unique = []
    for p in combos:
        key = json.dumps(p, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    print(f"combo count={len(unique)}", flush=True)
    combo_train = [evaluate(f"combo_{i}", "combo", p) for i, p in enumerate(unique)]

    top = sorted(
        [r for r in combo_train if r["metrics"]["trades"] >= MIN_TRADES and r["metrics"]["expectancy"] > 0],
        key=lambda r: r["score"],
        reverse=True,
    )[:8]
    if not top:
        top = sorted(combo_train, key=lambda r: r["score"], reverse=True)[:5]

    print("\n--- Validation ---", flush=True)
    val_rows = []
    for tr in top:
        vr = evaluate(tr["label"] + "_val", "combo_val", tr["params"], dataset="val")
        val_rows.append({**vr, "train_score": tr["score"], "train_metrics": tr["metrics"]})

    def pick_rec(vrows):
        if not vrows:
            return None
        # Prefer positive expectancy on val when enough trades; else train score + val trades
        scored = sorted(
            vrows,
            key=lambda r: (
                1 if r["metrics"]["expectancy"] > 0 else 0,
                r["score"],
                r["metrics"]["trades"],
                r.get("train_score", 0),
            ),
            reverse=True,
        )
        return scored[0]

    recommended = pick_rec(val_rows)
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
        "baseline": {"params": base, "full": base_full, "train": base_train},
        "entry_pack": entry_best,
        "ofat_best": {k: ({"label": v["label"], "score": v["score"], "metrics": v["metrics"], "params": v["params"]} if v else None) for k, v in picks.items()},
        "top10_train": ranked[:10],
        "recommended": recommended,
        "recommended_oos": rec_oos,
        "recommended_full": rec_full,
        "notes": [
            "Baseline current defaults: 0 trades on 60d Angel One Bank Nifty 1m — VWAP dist 0.35% + ST + momentum block entries.",
            "Entry filters optimized first to create a tradeable set; then ATR stop/target/hold optimized.",
            "Supertrend enrich defaults: period=10, multiplier=3.0.",
            "Risk ATR overrides apply only during Bank Nifty momentum_burst patch (other strategies unchanged).",
        ],
    }
    out_path = os.environ.get("REPORT_PATH", "/tmp/optimize_scalp_ad005_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote {out_path}", flush=True)

    print("\n=== TOP 10 TRAIN ===", flush=True)
    for i, r in enumerate(ranked[:10], 1):
        m = r["metrics"]
        print(f"{i:2}. [{r['group']}] {r['label']} sc={r['score']} WR={m['win_rate']}% PF={m['profit_factor']} tr={m['trades']} PnL={m['total_pnl']} DD={m['max_drawdown']}", flush=True)

    if recommended:
        print("\n=== RECOMMENDED ===", flush=True)
        print(
            json.dumps(
                {
                    "params": recommended["params"],
                    "val": recommended["metrics"],
                    "oos": rec_oos["metrics"] if rec_oos else None,
                    "full": rec_full["metrics"] if rec_full else None,
                },
                indent=2,
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
