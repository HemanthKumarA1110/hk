#!/usr/bin/env python3
"""SCALP-AD-006 (VWAP Bounce) parameter optimization — Bank Nifty.

    PYTHONUNBUFFERED=1 python /app/scripts/optimize_scalp_ad006.py
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

STRATEGY_CODE = "SCALP-AD-006"
INSTRUMENT_KEY = "banknifty"
BACKTEST_DAYS = int(os.environ.get("BACKTEST_DAYS", "60"))
SAMPLE_BARS = int(os.environ.get("SAMPLE_BARS", "25000"))
MIN_TRADES = int(os.environ.get("MIN_TRADES", "8"))
CANDLE_CACHE = os.environ.get("CANDLE_CACHE", "/tmp/ad006_candles.pkl")

_P: dict[str, Any] = {}
_SESSION = "both"
_REGIME_ALLOW: set[str] | None = None  # None = all


def baseline_params() -> dict[str, Any]:
    # Matches evaluate_vwap_bounce as implemented today (incl. stop/target mults).
    return {
        "vb_near_atr_mult": 0.25,
        "vb_near_pct": 0.0,  # 0 = use ATR proximity only
        "vb_call_prev_rsi_max": 45,  # prev < this
        "vb_call_rsi_min": 45,
        "vb_call_rsi_max": 58,
        "vb_put_prev_rsi_min": 55,  # prev > this
        "vb_put_rsi_min": 42,
        "vb_put_rsi_max": 55,
        "vb_rsi_turn_min": 0.0,
        "vb_candle_mode": "color",  # color | body40 | body50 | body60 | off
        "vb_multi_bar": 1,  # 1 = current only, 2 = two consecutive
        "vb_side_mode": "touch",  # touch | displace | cross
        "vb_side_displace_atr": 0.05,
        "vb_stop_atr_mult": 1.14,  # 1.2 * 0.95 from code
        "vb_stop_floor_pct": 0.0002,
        "vb_target_atr_mult": 0.225,  # 0.5 * 0.45 from code
        "vb_min_target_pts": 10.0,
        "vb_max_hold_bars": 6,  # max(6, 8-2)
        "vb_require_regime": False,
    }


def legacy_doc_params() -> dict[str, Any]:
    """Documented RISK_PROFILES 1.2/0.5/8 without evaluate mults (A/B)."""
    p = baseline_params()
    p.update({"vb_stop_atr_mult": 1.20, "vb_target_atr_mult": 0.50, "vb_max_hold_bars": 8})
    return p


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
    for path in (CANDLE_CACHE, "/tmp/ad005_candles.pkl", "/tmp/bt003_candles.pkl", "/tmp/bt002_candles.pkl"):
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
    from trading_shared.strategies.scalping_desk.market_context import detect_regime_from_candles
    from trading_shared.strategies.scalping_desk.strategies import _build_signal

    _orig_window = bts._active_battle_window
    _orig_risk = eng.compute_scalp_risk
    _orig_hold = eng.max_hold_bars

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
        # Keep profile ATR multiples; evaluate_patched applies vb_* via stop/target_mult.
        # Only override floors when tuning.
        stop, tgt = _orig_risk(spot, atr, instrument_key)
        if instrument_key == "banknifty" and _P:
            floor = float(spot) * float(_P.get("vb_stop_floor_pct") or 0.0002)
            min_tgt = float(_P.get("vb_min_target_pts") or 10.0)
            stop = max(float(stop), floor)
            tgt = max(float(tgt), min_tgt)
            return round(stop, 2), round(tgt, 2)
        return stop, tgt

    def hold_patched(instrument_key):
        if instrument_key == "banknifty" and _P:
            return int(_P["vb_max_hold_bars"])
        return _orig_hold(instrument_key)

    def candle_ok(row, direction: str, mode: str) -> bool:
        o, c, h, l = float(row["open"]), float(row["close"]), float(row["high"]), float(row["low"])
        body = abs(c - o)
        rng = max(h - l, 1e-9)
        body_pct = body / rng
        if mode == "off":
            return True
        if mode == "color":
            return (c > o) if direction == "CALL" else (c < o)
        need = {"body40": 0.40, "body50": 0.50, "body60": 0.60}.get(mode, 0.0)
        if direction == "CALL":
            return c > o and body_pct >= need
        return c < o and body_pct >= need

    def multi_ok(data, direction: str, n: int, mode: str) -> bool:
        if n <= 1:
            return candle_ok(data.iloc[-1], direction, mode)
        if len(data) < n:
            return False
        return all(candle_ok(data.iloc[-i], direction, mode if mode != "off" else "color") for i in range(1, n + 1))

    def near_ok(spot, vwap, atr, p) -> bool:
        atr_m = float(p["vb_near_atr_mult"])
        pct = float(p.get("vb_near_pct") or 0)
        d = abs(spot - vwap)
        ok_atr = d <= atr * atr_m if atr_m > 0 else True
        ok_pct = d / max(spot, 1) * 100 <= pct if pct > 0 else True
        if atr_m > 0 and pct > 0:
            return ok_atr or ok_pct  # either method
        if pct > 0:
            return ok_pct
        return ok_atr

    def side_ok(spot, vwap, atr, direction: str, p) -> bool:
        mode = str(p.get("vb_side_mode") or "touch")
        disp = float(p.get("vb_side_displace_atr") or 0) * atr
        if mode == "touch":
            return spot >= vwap if direction == "CALL" else spot <= vwap
        if mode == "displace":
            return spot >= vwap + disp if direction == "CALL" else spot <= vwap - disp
        # cross: allow either side within near band (mean-reversion after cross still near VWAP)
        return True

    def evaluate_patched(df, timeframe, option_chain, lot_size, *, enriched=False, instrument_key="nifty50", params=None, skip_session=False):
        if len(df) < 21:
            return None
        # Keep skip_session architecture: when False, use session check (live).
        if not skip_session:
            from trading_shared.strategies.scalping_desk.market_context import in_trading_session

            if not in_trading_session():
                return None

        p = {**baseline_params(), **(_P or {})}
        if isinstance((params or {}).get("vwap_bounce"), dict):
            p.update(params["vwap_bounce"])

        from trading_shared.strategies.scalping_desk.engine import enrich_candles

        data = df if enriched else enrich_candles(df)
        row = data.iloc[-1]
        prev = data.iloc[-2]
        spot = float(row["close"])
        atr = float(row["atr"] or spot * 0.002)
        vwap = float(row["vwap"])
        rsi_val = float(row["rsi14"])
        prev_rsi = float(prev["rsi14"])

        if _REGIME_ALLOW is not None:
            try:
                reg = detect_regime_from_candles(data.tail(60)).value
            except Exception:
                reg = "UNKNOWN"
            if str(reg).lower() not in {x.lower() for x in _REGIME_ALLOW} and str(reg).upper() not in {x.upper() for x in _REGIME_ALLOW}:
                # also accept enum-like
                if reg not in _REGIME_ALLOW:
                    return None

        if not near_ok(spot, vwap, atr, p):
            return None

        turn = float(p.get("vb_rsi_turn_min") or 0)
        call_turn_ok = (rsi_val - prev_rsi) >= turn
        put_turn_ok = (prev_rsi - rsi_val) >= turn
        candle_mode = str(p.get("vb_candle_mode") or "color")
        multi = int(p.get("vb_multi_bar") or 1)

        call_ok = (
            side_ok(spot, vwap, atr, "CALL", p)
            and prev_rsi < float(p["vb_call_prev_rsi_max"])
            and float(p["vb_call_rsi_min"]) <= rsi_val <= float(p["vb_call_rsi_max"])
            and call_turn_ok
            and multi_ok(data, "CALL", multi, candle_mode)
        )
        put_ok = (
            side_ok(spot, vwap, atr, "PUT", p)
            and prev_rsi > float(p["vb_put_prev_rsi_min"])
            and float(p["vb_put_rsi_min"]) <= rsi_val <= float(p["vb_put_rsi_max"])
            and put_turn_ok
            and multi_ok(data, "PUT", multi, candle_mode)
        )
        if not call_ok and not put_ok:
            return None

        # Express desired ATR multiples via stop/target mults relative to RISK_PROFILES base.
        from trading_shared.strategies.scalping_desk.constants import RISK_PROFILES

        profile = RISK_PROFILES.get(instrument_key, RISK_PROFILES.get("banknifty", {}))
        base_stop = float(profile.get("stop_atr_mult") or 1.2)
        base_tgt = float(profile.get("target_atr_mult") or 0.5)
        want_stop = float(p["vb_stop_atr_mult"])
        want_tgt = float(p["vb_target_atr_mult"])
        stop_mult = want_stop / max(base_stop, 1e-9)
        target_mult = want_tgt / max(base_tgt, 1e-9)

        return _build_signal(
            strategy_id="vwap_bounce",
            strategy_label="VWAP Bounce",
            signal_type="CALL" if call_ok else "PUT",
            data=data,
            timeframe=timeframe,
            option_chain=option_chain,
            instrument_key=instrument_key,
            conditions=["near_vwap", "rsi_reversal", "ranging_bounce"],
            stop_mult=stop_mult,
            target_mult=target_mult,
            hold_bars=int(p["vb_max_hold_bars"]),
        )

    bts._active_battle_window = window_patched
    eng.compute_scalp_risk = risk_patched
    strat.compute_scalp_risk = risk_patched
    eng.max_hold_bars = hold_patched
    strat.max_hold_bars = hold_patched
    strat.evaluate_vwap_bounce = evaluate_patched
    strat.STRATEGY_REGISTRY["vwap_bounce"]["evaluate"] = evaluate_patched


def set_cfg(params: dict[str, Any], *, session: str = "both", regimes: set[str] | None = None) -> None:
    global _P, _SESSION, _REGIME_ALLOW
    _P = dict(params)
    _SESSION = session
    _REGIME_ALLOW = regimes


def run_bt(candles, lot: int, capital: float) -> dict[str, Any]:
    from trading_shared.strategies.scalping_desk.backtest import run_backtest

    return run_backtest(
        candles,
        "1m",
        lot,
        capital,
        strategy_code=STRATEGY_CODE,
        instrument_key=INSTRUMENT_KEY,
        params={"vwap_bounce": dict(_P)},
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
        k: {"wr": subset(v)[0], "n": subset(v)[1], "pnl": round(sum(float(x.get("pnl") or 0) for x in v), 2)}
        for k, v in regimes.items()
    }
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
        "call_wr": subset(calls)[0],
        "call_n": subset(calls)[1],
        "put_wr": subset(puts)[0],
        "put_n": subset(puts)[1],
        "morning_wr": subset(morning)[0],
        "morning_n": subset(morning)[1],
        "afternoon_wr": subset(afternoon)[0],
        "afternoon_n": subset(afternoon)[1],
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
    return wr * 1.8 + pf * 18.0 + max(min(exp / 200.0, 20.0), -20.0) + trade_score + max(min(pnl / 5000.0, 15.0), -15.0) - min(dd / 1000.0, 40.0)


def split_wf(candles):
    n = len(candles)
    i1, i2 = int(n * 0.60), int(n * 0.80)
    return candles.iloc[:i1].reset_index(drop=True), candles.iloc[i1:i2].reset_index(drop=True), candles.iloc[i2:].reset_index(drop=True)


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
    print("\n--- BASELINE (code as-is: near 0.25 ATR, stop~1.14 ATR, tgt~0.225 ATR, hold 6) ---", flush=True)
    base_full = metrics(run_bt(candles, lot, capital), candles)
    base_train = metrics(run_bt(train, lot, capital), train)
    base_val = metrics(run_bt(val, lot, capital), val)
    base_oos = metrics(run_bt(oos, lot, capital), oos)
    print(json.dumps({"full": base_full, "train": base_train, "val": base_val, "oos": base_oos}, indent=2), flush=True)
    base_score = balanced_score(base_train, max(base_train["trades"], 15))

    rows: list[dict[str, Any]] = []

    def evaluate(label, group, params, *, dataset="train", session="both", regimes=None):
        set_cfg(params, session=session, regimes=regimes)
        data = {"train": train, "val": val, "oos": oos, "full": candles}[dataset]
        m = metrics(run_bt(data, lot, capital), data if dataset != "full" else candles)
        ref = max(base_train["trades"], 15) if dataset == "train" else max(base_full["trades"], 15)
        sc = balanced_score(m, ref)
        row = {"label": label, "group": group, "dataset": dataset, "params": deepcopy(params), "metrics": m, "score": round(sc, 2), "session": session}
        rows.append(row)
        print(
            f"{group:12} {label:28} [{dataset}] tr={m['trades']:>3} WR={m['win_rate']:>5}% "
            f"PF={m['profit_factor']:>5} EXP={m['expectancy']:>8} PnL={m['total_pnl']:>9} DD={m['max_drawdown']:>8} sc={sc:>6.1f}",
            flush=True,
        )
        return row

    def best(group):
        g = [r for r in rows if r["group"] == group and r["dataset"] == "train" and r["metrics"]["trades"] >= MIN_TRADES]
        if not g:
            g = [r for r in rows if r["group"] == group and r["dataset"] == "train" and r["metrics"]["trades"] >= 3]
        return max(g, key=lambda r: r["score"]) if g else None

    # 1 VWAP proximity ATR
    print("\n--- 1 VWAP proximity ATR ---", flush=True)
    for m in [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60]:
        p = deepcopy(base)
        p["vb_near_atr_mult"] = m
        p["vb_near_pct"] = 0.0
        evaluate(f"near_atr_{m}", "near_atr", p)

    print("\n--- 3 VWAP proximity % ---", flush=True)
    for pct in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35]:
        p = deepcopy(base)
        p["vb_near_atr_mult"] = 0.0
        p["vb_near_pct"] = pct
        evaluate(f"near_pct_{pct}", "near_pct", p)

    # Pick working near for subsequent OFAT
    near_best = best("near_atr") or best("near_pct")
    work = deepcopy(base)
    if near_best and near_best["metrics"]["trades"] >= 3:
        work["vb_near_atr_mult"] = near_best["params"]["vb_near_atr_mult"]
        work["vb_near_pct"] = near_best["params"]["vb_near_pct"]
        print(f"Using near from {near_best['label']} for downstream OFAT", flush=True)

    # If still few trades, loosen near to 0.40 ATR as working base
    set_cfg(work)
    probe = metrics(run_bt(train, lot, capital), train)
    if probe["trades"] < MIN_TRADES:
        work["vb_near_atr_mult"] = 0.40
        work["vb_near_pct"] = 0.0
        print("Loosened near to 0.40 ATR for OFAT viability", flush=True)

    print("\n--- 4 CALL RSI ---", flush=True)
    for prev in [40, 42, 43, 44, 45, 46, 48, 50]:
        p = deepcopy(work)
        p["vb_call_prev_rsi_max"] = prev
        evaluate(f"call_prev_{prev}", "call_prev", p)
    for lo, hi in [(43, 55), (44, 56), (45, 57), (45, 58), (46, 58), (46, 60), (48, 60), (48, 62)]:
        p = deepcopy(work)
        p["vb_call_rsi_min"] = lo
        p["vb_call_rsi_max"] = hi
        evaluate(f"call_cur_{lo}_{hi}", "call_cur", p)

    print("\n--- 5 PUT RSI ---", flush=True)
    for prev in [52, 54, 55, 56, 57, 58, 60]:
        p = deepcopy(work)
        p["vb_put_prev_rsi_min"] = prev
        evaluate(f"put_prev_{prev}", "put_prev", p)
    for lo, hi in [(40, 52), (41, 53), (42, 54), (42, 55), (43, 55), (44, 56), (44, 58), (45, 58)]:
        p = deepcopy(work)
        p["vb_put_rsi_min"] = lo
        p["vb_put_rsi_max"] = hi
        evaluate(f"put_cur_{lo}_{hi}", "put_cur", p)

    print("\n--- 6 RSI turn ---", flush=True)
    for t in [0, 1, 2, 3, 4, 5]:
        p = deepcopy(work)
        p["vb_rsi_turn_min"] = float(t)
        evaluate(f"turn_{t}", "rsi_turn", p)

    print("\n--- 7 RSI extremes ---", flush=True)
    for prev in [35, 38, 40, 42, 45]:
        p = deepcopy(work)
        p["vb_call_prev_rsi_max"] = prev
        evaluate(f"call_ext_{prev}", "call_ext", p)
    for prev in [55, 58, 60, 62, 65]:
        p = deepcopy(work)
        p["vb_put_prev_rsi_min"] = prev
        evaluate(f"put_ext_{prev}", "put_ext", p)

    print("\n--- 8 Candle ---", flush=True)
    for mode in ["color", "body40", "body50", "body60", "off"]:
        p = deepcopy(work)
        p["vb_candle_mode"] = mode
        evaluate(f"candle_{mode}", "candle", p)

    print("\n--- 9 Multi-bar ---", flush=True)
    for n in [1, 2]:
        p = deepcopy(work)
        p["vb_multi_bar"] = n
        evaluate(f"multi_{n}", "multi", p)

    print("\n--- 10 VWAP side ---", flush=True)
    for mode in ["touch", "displace", "cross"]:
        p = deepcopy(work)
        p["vb_side_mode"] = mode
        evaluate(f"side_{mode}", "side", p)

    print("\n--- 11-12 ATR stop/target ---", flush=True)
    for s in [0.60, 0.70, 0.80, 0.90, 1.00, 1.10, 1.14, 1.20, 1.30, 1.40, 1.50, 1.75, 2.00]:
        p = deepcopy(work)
        p["vb_stop_atr_mult"] = s
        evaluate(f"sl_{s}", "stop_atr", p)
    for f in [0.0001, 0.00015, 0.0002, 0.00025, 0.0003]:
        p = deepcopy(work)
        p["vb_stop_floor_pct"] = f
        evaluate(f"sl_floor_{f}", "stop_floor", p)
    for t in [0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00, 1.20, 1.50]:
        p = deepcopy(work)
        p["vb_target_atr_mult"] = t
        evaluate(f"tgt_{t}", "target_atr", p)
    # also test documented 0.225 current
    p = deepcopy(work)
    p["vb_target_atr_mult"] = 0.225
    evaluate("tgt_0.225", "target_atr", p)
    for f in [5, 8, 10, 12, 15, 20]:
        p = deepcopy(work)
        p["vb_min_target_pts"] = float(f)
        evaluate(f"tgt_floor_{f}", "target_floor", p)

    sl_c = sorted([r for r in rows if r["group"] == "stop_atr" and r["metrics"]["trades"] >= 5], key=lambda r: r["score"], reverse=True)[:4]
    tg_c = sorted([r for r in rows if r["group"] == "target_atr" and r["metrics"]["trades"] >= 5], key=lambda r: r["score"], reverse=True)[:4]
    print("\n--- 13 RR combos ---", flush=True)
    for a, b in product(sl_c, tg_c):
        p = deepcopy(work)
        p["vb_stop_atr_mult"] = a["params"]["vb_stop_atr_mult"]
        p["vb_target_atr_mult"] = b["params"]["vb_target_atr_mult"]
        evaluate(f"rr_{p['vb_stop_atr_mult']}_{p['vb_target_atr_mult']}", "rr", p)

    print("\n--- 14 Max hold ---", flush=True)
    for h in [2, 3, 4, 5, 6, 7, 8, 10, 12, 15]:
        p = deepcopy(work)
        p["vb_max_hold_bars"] = h
        evaluate(f"hold_{h}", "hold", p)

    print("\n--- 16 Regime filter ---", flush=True)
    for name, regs in [
        ("all", None),
        ("ranging", {"ranging", "RANGING"}),
        ("ranging_lowvol", {"ranging", "RANGING", "low_volatility", "LOW_VOLATILITY"}),
        ("lowvol", {"low_volatility", "LOW_VOLATILITY"}),
    ]:
        evaluate(f"reg_{name}", "regime", deepcopy(work), regimes=regs)

    print("\n--- 17 Session ---", flush=True)
    for sess in ["both", "morning", "afternoon"]:
        evaluate(f"sess_{sess}", "session", deepcopy(work), session=sess)

    picks = {g: best(g) for g in [
        "near_atr", "near_pct", "call_prev", "call_cur", "put_prev", "put_cur", "rsi_turn",
        "candle", "multi", "side", "stop_atr", "target_atr", "rr", "hold", "regime", "session",
    ]}
    print("\n--- Best OFAT ---", flush=True)
    for g, r in picks.items():
        if r:
            print(f"  {g}: {r['label']} sc={r['score']} WR={r['metrics']['win_rate']} tr={r['metrics']['trades']}", flush=True)

    # Build refined
    rec = deepcopy(work)
    for group, keys in [
        ("near_atr", ["vb_near_atr_mult", "vb_near_pct"]),
        ("near_pct", ["vb_near_atr_mult", "vb_near_pct"]),
        ("call_prev", ["vb_call_prev_rsi_max"]),
        ("call_cur", ["vb_call_rsi_min", "vb_call_rsi_max"]),
        ("put_prev", ["vb_put_prev_rsi_min"]),
        ("put_cur", ["vb_put_rsi_min", "vb_put_rsi_max"]),
        ("rsi_turn", ["vb_rsi_turn_min"]),
        ("candle", ["vb_candle_mode"]),
        ("multi", ["vb_multi_bar"]),
        ("side", ["vb_side_mode"]),
        ("rr", ["vb_stop_atr_mult", "vb_target_atr_mult"]),
        ("stop_atr", ["vb_stop_atr_mult"]),
        ("target_atr", ["vb_target_atr_mult"]),
        ("hold", ["vb_max_hold_bars"]),
    ]:
        r = picks.get(group)
        if not r:
            continue
        if r["score"] < base_score - 2 and r["metrics"]["trades"] < max(MIN_TRADES, base_train["trades"]):
            continue
        if r["metrics"]["trades"] < 3:
            continue
        for k in keys:
            if k in r["params"]:
                rec[k] = r["params"][k]

    # Prefer ATR near over pct if both set — clear conflict
    if float(rec.get("vb_near_pct") or 0) > 0 and float(rec.get("vb_near_atr_mult") or 0) > 0:
        # keep whichever OFAT scored higher
        na, np_ = picks.get("near_atr"), picks.get("near_pct")
        if na and np_ and np_["score"] > na["score"]:
            rec["vb_near_atr_mult"] = 0.0
        else:
            rec["vb_near_pct"] = 0.0

    print("\n--- Refined combos ---", flush=True)
    combos = [deepcopy(base), deepcopy(work), deepcopy(rec), legacy_doc_params()]
    for d_near in [-0.05, 0.0, 0.05]:
        p = deepcopy(rec)
        if float(p.get("vb_near_atr_mult") or 0) > 0:
            p["vb_near_atr_mult"] = max(0.10, round(float(p["vb_near_atr_mult"]) + d_near, 2))
        combos.append(p)
    for d_sl, d_tg in product([-0.2, 0.0, 0.2], [-0.1, 0.0, 0.1]):
        p = deepcopy(rec)
        p["vb_stop_atr_mult"] = max(0.6, round(float(p["vb_stop_atr_mult"]) + d_sl, 2))
        p["vb_target_atr_mult"] = max(0.2, round(float(p["vb_target_atr_mult"]) + d_tg, 2))
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
        return sorted(
            vrows,
            key=lambda r: (1 if r["metrics"]["expectancy"] > 0 else 0, r["score"], r["metrics"]["trades"], r.get("train_score", 0)),
            reverse=True,
        )[0]

    recommended = pick_rec(val_rows)
    rec_oos = rec_full = None
    if recommended:
        print("\n--- OOS + Full ---", flush=True)
        rec_oos = evaluate("recommended_oos", "oos", recommended["params"], dataset="oos")
        rec_full = evaluate("recommended_full", "full", recommended["params"], dataset="full")

    # Loss quality on baseline full
    set_cfg(base)
    base_res = run_bt(candles, lot, capital)
    losses = [t for t in (base_res.get("trades") or []) if float(t.get("pnl") or 0) <= 0]
    aft_l = sum(1 for t in losses if (lambda h: h and 13 * 60 + 30 <= h <= 14 * 60 + 45)(_hhmm(str(t.get("entry_time") or ""))))

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
        "loss_quality": {"losing_trades": len(losses), "afternoon_losses": aft_l, "morning_losses": len(losses) - aft_l},
        "notes": [
            "Code baseline uses evaluate_vwap_bounce stop_mult=0.95 target_mult=0.45 hold=max(6,8-2) on RISK_PROFILES → ~1.14/0.225 ATR, hold 6.",
            "Keep mean-reversion identity: no Supertrend/EMA-cross/momentum indicators added.",
            "Walk-forward 60/20/20 by bar order.",
        ],
    }
    out_path = os.environ.get("REPORT_PATH", "/tmp/optimize_scalp_ad006_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote {out_path}", flush=True)

    print("\n=== TOP 10 TRAIN ===", flush=True)
    for i, r in enumerate(ranked[:10], 1):
        m = r["metrics"]
        print(f"{i:2}. [{r['group']}] {r['label']} sc={r['score']} WR={m['win_rate']}% PF={m['profit_factor']} tr={m['trades']} PnL={m['total_pnl']} DD={m['max_drawdown']}", flush=True)

    if recommended:
        print("\n=== RECOMMENDED ===", flush=True)
        print(json.dumps({"params": recommended["params"], "val": recommended["metrics"], "oos": rec_oos["metrics"] if rec_oos else None, "full": rec_full["metrics"] if rec_full else None}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
