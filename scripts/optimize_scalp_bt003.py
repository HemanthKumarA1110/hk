#!/usr/bin/env python3
"""SCALP-BT-003 (EMA Crossover + RSI) parameter optimization — Bank Nifty.

Uses existing run_backtest. Does not modify strategy defaults until results are reviewed.

    PYTHONUNBUFFERED=1 python /app/scripts/optimize_scalp_bt003.py
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
from typing import Any, Callable

STRATEGY_CODE = "SCALP-BT-003"
INSTRUMENT_KEY = "banknifty"
BACKTEST_DAYS = int(os.environ.get("BACKTEST_DAYS", "60"))
SAMPLE_BARS = int(os.environ.get("SAMPLE_BARS", "25000"))
MIN_TRADES = int(os.environ.get("MIN_TRADES", "8"))
CANDLE_CACHE = os.environ.get("CANDLE_CACHE", "/tmp/bt003_candles.pkl")

FAST_EMAS = [5, 7, 8, 9, 10, 12, 13]
SLOW_EMAS = [18, 20, 21, 24, 26, 30]
LOOKBACKS = [1, 2, 3, 4, 5, 6]
CALL_RSI = [(50, 60), (52, 60), (53, 60), (54, 62), (55, 63), (55, 65), (52, 64), (54, 66)]
PUT_RSI = [(35, 45), (38, 46), (40, 46), (40, 48), (38, 48), (35, 47), (36, 44)]
VOL_RATIOS = [0.0, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.35, 1.50]
SEP_PCTS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
VWAP_DIST = [0.0, 0.05, 0.10, 0.15, 0.20]
STOPS = [40, 45, 50, 55, 60, 65, 70, 75, 80, 90]
TARGETS = [90, 100, 110, 120, 130, 140, 150, 160, 180]
HOLDS = [3, 4, 5, 6, 7, 8, 10, 12, 15]
MOM_ATR = [0.05, 0.10, 0.15, 0.20, 0.25]

# Runtime overrides applied via monkeypatches
_EMA_FAST = 9
_EMA_SLOW = 21
_ALLOW_EXPIRY = False
_SESSION_MODE = "both"  # both | morning | afternoon
_EXTRA: dict[str, Any] = {}


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
    # Prefer BT-003 cache; fall back to BT-002 cache if present.
    for path in (CANDLE_CACHE, "/tmp/bt002_candles.pkl"):
        if os.path.isfile(path) and os.environ.get("FORCE_RELOAD") != "1":
            with open(path, "rb") as f:
                payload = pickle.load(f)
            print(f"Loaded cache {path}: bars={len(payload['df']):,} source={payload['source']}", flush=True)
            if path != CANDLE_CACHE:
                with open(CANDLE_CACHE, "wb") as f:
                    pickle.dump(payload, f)
            return payload["df"], payload["source"], payload["from_date"], payload["to_date"]

    df, source, from_date, to_date = asyncio.run(load_candles(user_id))
    with open(CANDLE_CACHE, "wb") as f:
        pickle.dump({"df": df, "source": source, "from_date": from_date, "to_date": to_date}, f)
    print(f"Cached candles → {CANDLE_CACHE}", flush=True)
    return df, source, from_date, to_date


def baseline_params() -> dict[str, Any]:
    from trading_shared.strategies.scalping_desk.ema_crossover_tuning import EMA_CROSSOVER_BANK_DEFAULTS

    return dict(EMA_CROSSOVER_BANK_DEFAULTS)


def install_patches() -> None:
    """Patch enrich / expiry / session / evaluate for opt-only extras."""
    import trading_shared.strategies.scalping_desk.backtest as bt
    import trading_shared.strategies.scalping_desk.battle_tested_scalp as bts
    import trading_shared.strategies.scalping_desk.engine as eng
    from trading_shared.strategies.scalping_desk.ema_crossover_tuning import merge_ema_crossover_params
    from trading_shared.strategies.scalping_desk.strategies import _two_bar_momentum

    _orig_enrich = eng.enrich_candles
    _orig_expiry = bts.is_expiry_day
    _orig_window = bts._active_battle_window
    _orig_eval = bts.evaluate_ema_crossover_rsi

    def enrich_patched(df):
        out = _orig_enrich(df)
        if _EMA_FAST != 9 or _EMA_SLOW != 21:
            close = out["close"].astype(float)
            out = out.copy()
            out["ema9"] = close.ewm(span=_EMA_FAST, adjust=False).mean()
            out["ema21"] = close.ewm(span=_EMA_SLOW, adjust=False).mean()
        return out

    def is_expiry_patched(ts, instrument_key):
        if _ALLOW_EXPIRY:
            return False
        return _orig_expiry(ts, instrument_key)

    def window_patched(ts):
        label = _orig_window(ts)
        if _SESSION_MODE == "both":
            return label
        if label is None:
            return None
        if _SESSION_MODE == "morning" and label.startswith("09:20"):
            return label
        if _SESSION_MODE == "afternoon" and label.startswith("13:30"):
            return label
        return None

    def momentum_ok(data, direction: str, mode: str, atr_mult: float) -> bool:
        if mode == "off":
            return True
        if mode == "color" or mode == "a":
            return _two_bar_momentum(data, direction)
        if len(data) < 3:
            return False
        c2, c3 = data.iloc[-2], data.iloc[-1]
        if mode == "close_chain" or mode == "b":
            if direction == "CALL":
                return float(c3["close"]) > float(c2["close"]) and float(c2["close"]) > float(c2["open"])
            return float(c3["close"]) < float(c2["close"]) and float(c2["close"]) < float(c2["open"])
        # ATR move (mode c)
        atr = float(c3.get("atr") or 0) or max(float(c3["close"]) * 0.001, 1.0)
        move = abs(float(c3["close"]) - float(c2["open"]))
        if move < atr * atr_mult:
            return False
        return _two_bar_momentum(data, direction)

    def evaluate_patched(
        df,
        timeframe,
        option_chain,
        lot_size,
        *,
        enriched=False,
        instrument_key="nifty50",
        params=None,
        skip_session=False,
    ):
        if instrument_key != "banknifty":
            return _orig_eval(
                df,
                timeframe,
                option_chain,
                lot_size,
                enriched=enriched,
                instrument_key=instrument_key,
                params=params,
                skip_session=skip_session,
            )
        if len(df) < 25:
            return None
        p = merge_ema_crossover_params(params)
        # Opt-only extras
        p = {**p, **_EXTRA}
        data = df if enriched else enrich_patched(df)
        row = data.iloc[-1]
        ts = row.get("timestamp")
        if not skip_session and not bts.in_battle_session(ts, df=data, instrument_key=instrument_key):
            return None
        if (not _ALLOW_EXPIRY) and bts._expiry_blocks_entry(ts, instrument_key):
            return None

        ema9 = float(row["ema9"])
        ema21 = float(row["ema21"])
        rsi_val = float(row["rsi14"])
        spot = float(row["close"])
        vwap = float(row.get("vwap", spot))
        vol_ratio = float(row.get("volume_ratio") or 0)
        vol_spike = bool(row.get("vol_spike"))

        sep_pct = float(p.get("ema_min_separation_pct") or 0)
        if sep_pct > 0 and abs(ema9 - ema21) / max(spot, 1) * 100 < sep_pct:
            return None
        vol_min = float(p.get("ema_vol_min") or 0)
        use_spike = bool(p.get("ema_use_vol_spike"))
        if vol_min > 0 or use_spike:
            vol_ok = vol_ratio >= vol_min or (use_spike and vol_spike)
            if not vol_ok:
                return None

        lookback = int(p.get("ema_cross_lookback") or 3)
        call_rsi_min = int(p.get("ema_rsi_call_min") or 50)
        call_rsi_max = int(p.get("ema_rsi_call_max") or 65)
        put_rsi_min = int(p.get("ema_rsi_put_min") or 35)
        put_rsi_max = int(p.get("ema_rsi_put_max") or 50)
        need_vwap = bool(p.get("ema_require_vwap", True))
        need_momentum = bool(p.get("ema_require_two_bar_momentum", True))
        mom_mode = str(p.get("ema_momentum_mode") or ("a" if need_momentum else "off"))
        mom_atr = float(p.get("ema_momentum_atr") or 0.0)
        require_rsi_slope = bool(p.get("ema_require_rsi_slope", False))
        vwap_dist_pct = float(p.get("ema_vwap_distance_pct") or 0.0)

        if require_rsi_slope and len(data) >= 2:
            prev_rsi = float(data.iloc[-2]["rsi14"])
        else:
            prev_rsi = rsi_val

        dist_ok_call = True
        dist_ok_put = True
        if vwap_dist_pct > 0:
            dist = abs(spot - vwap) / max(spot, 1) * 100
            dist_ok_call = dist >= vwap_dist_pct and spot > vwap
            dist_ok_put = dist >= vwap_dist_pct and spot < vwap

        call_ok = (
            bts._recent_cross(data, "CALL", lookback=lookback)
            and ema9 > ema21
            and call_rsi_min <= rsi_val <= call_rsi_max
            and (not need_vwap or spot > vwap)
            and dist_ok_call
            and (not require_rsi_slope or rsi_val > prev_rsi)
            and momentum_ok(data, "CALL", mom_mode if need_momentum or mom_mode != "off" else "off", mom_atr)
        )
        put_ok = (
            bts._recent_cross(data, "PUT", lookback=lookback)
            and ema9 < ema21
            and put_rsi_min <= rsi_val <= put_rsi_max
            and (not need_vwap or spot < vwap)
            and dist_ok_put
            and (not require_rsi_slope or rsi_val < prev_rsi)
            and momentum_ok(data, "PUT", mom_mode if need_momentum or mom_mode != "off" else "off", mom_atr)
        )
        if not call_ok and not put_ok:
            return None

        signal_type = "CALL" if call_ok else "PUT"
        risk = bts.battle_risk(instrument_key)
        risk = {
            **risk,
            "stop_pts": float(p.get("ema_stop_pts") or risk["stop_pts"]),
            "target_pts": float(p.get("ema_target_pts") or risk["target_pts"]),
            "max_hold_bars": int(p.get("ema_max_hold_bars") or risk["max_hold_bars"]),
        }
        return bts._build_battle_signal(
            strategy_id="ema_crossover_rsi",
            strategy_label="EMA Crossover + RSI",
            signal_type=signal_type,
            data=data,
            timeframe=timeframe,
            option_chain=option_chain,
            instrument_key=instrument_key,
            conditions=["ema_cross", "rsi_filter", "battle_session"],
            risk=risk,
        )

    eng.enrich_candles = enrich_patched
    bt.enrich_candles = enrich_patched
    bts.is_expiry_day = is_expiry_patched
    bts._active_battle_window = window_patched
    bts.evaluate_ema_crossover_rsi = evaluate_patched
    bts.BATTLE_REGISTRY["ema_crossover_rsi"]["evaluate"] = evaluate_patched


def set_ema_pair(fast: int, slow: int) -> None:
    global _EMA_FAST, _EMA_SLOW
    _EMA_FAST, _EMA_SLOW = fast, slow


def set_session(mode: str) -> None:
    global _SESSION_MODE
    _SESSION_MODE = mode


def set_allow_expiry(flag: bool) -> None:
    global _ALLOW_EXPIRY
    _ALLOW_EXPIRY = flag


def run_bt(candles, lot: int, capital: float, ema: dict[str, Any]) -> dict[str, Any]:
    from trading_shared.strategies.scalping_desk.backtest import run_backtest

    # Use run_backtest directly so vol/sep filters are not stripped by run_strategy_backtest.
    return run_backtest(
        candles,
        "1m",
        lot,
        capital,
        strategy_code=STRATEGY_CODE,
        instrument_key=INSTRUMENT_KEY,
        params={"ema_crossover": ema},
        max_loss_per_day=5000,
        max_trades_per_day=5,
        ai_entry=False,
        ai_exit=False,
    )


def _hhmm(ts: str) -> int | None:
    try:
        if "T" in ts:
            part = ts.split("T")[1][:5]
        elif " " in ts:
            part = ts.split(" ")[1][:5]
        else:
            return None
        hh, mm = part.split(":")
        return int(hh) * 60 + int(mm)
    except Exception:
        return None


def _weekday(ts: str) -> int | None:
    try:
        day = ts[:10]
        return date.fromisoformat(day).weekday()  # Mon=0
    except Exception:
        return None


def streak_stats(trades: list[dict[str, Any]]) -> dict[str, int]:
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


def metrics(result: dict[str, Any]) -> dict[str, Any]:
    trades = result.get("trades") or []
    n = int(result.get("total_trades") or 0)
    pnl = float(result.get("total_pnl") or 0)
    wr = float(result.get("win_rate") or 0)
    pf = float(result.get("profit_factor") or 0)
    dd = float(result.get("max_drawdown") or 0)
    avg_win = float(result.get("avg_profit_win") or 0)
    avg_loss = float(result.get("avg_loss_loss") or 0)
    wins = sum(1 for t in trades if float(t.get("pnl") or 0) > 0)
    losses = n - wins
    expectancy = round(pnl / n, 2) if n else 0.0
    streaks = streak_stats(trades)

    def subset_wr(rows):
        if not rows:
            return None, 0
        w = sum(1 for t in rows if float(t.get("pnl") or 0) > 0)
        return round(w / len(rows) * 100, 2), len(rows)

    calls = [t for t in trades if str(t.get("signal_type")).upper() == "CALL"]
    puts = [t for t in trades if str(t.get("signal_type")).upper() == "PUT"]
    morning, afternoon = [], []
    by_wd: dict[int, list] = {i: [] for i in range(5)}
    for t in trades:
        ts = str(t.get("entry_time") or "")
        hhmm = _hhmm(ts)
        wd = _weekday(ts)
        if hhmm is not None:
            if 9 * 60 + 20 <= hhmm <= 10 * 60 + 30:
                morning.append(t)
            elif 13 * 60 + 30 <= hhmm <= 14 * 60 + 45:
                afternoon.append(t)
        if wd is not None and wd < 5:
            by_wd[wd].append(t)

    call_wr, call_n = subset_wr(calls)
    put_wr, put_n = subset_wr(puts)
    morn_wr, morn_n = subset_wr(morning)
    aft_wr, aft_n = subset_wr(afternoon)
    weekday = {}
    for i, name in enumerate(["mon", "tue", "wed", "thu", "fri"]):
        w, nn = subset_wr(by_wd[i])
        weekday[name] = {"wr": w, "n": nn}

    return {
        "trades": n,
        "win_rate": wr,
        "wins": wins,
        "losses": losses,
        "profit_factor": pf,
        "expectancy": expectancy,
        "total_pnl": pnl,
        "max_drawdown": dd,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "call_wr": call_wr,
        "call_n": call_n,
        "put_wr": put_wr,
        "put_n": put_n,
        "morning_wr": morn_wr,
        "morning_n": morn_n,
        "afternoon_wr": aft_wr,
        "afternoon_n": aft_n,
        "weekday": weekday,
        **streaks,
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
    trade_score = max(0.0, min(trade_ratio, 2.0)) * 12.0
    if trade_ratio < 0.5:
        trade_score -= 20.0
    dd_penalty = min(dd / 1000.0, 40.0)
    exp_score = max(min(exp / 200.0, 20.0), -20.0)
    pnl_score = max(min(pnl / 5000.0, 15.0), -15.0)
    return wr * 1.8 + pf * 18.0 + exp_score + trade_score + pnl_score - dd_penalty


def split_walk_forward(candles):
    n = len(candles)
    i1 = int(n * 0.60)
    i2 = int(n * 0.80)
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
    print(f"bars={len(candles):,} source={source} range={from_date}→{to_date}", flush=True)
    if len(candles) < 500:
        print("Insufficient bars", flush=True)
        return 1

    train, val, oos = split_walk_forward(candles)
    print(f"walk-forward bars train={len(train)} val={len(val)} oos={len(oos)}", flush=True)

    base = baseline_params()
    set_ema_pair(9, 21)
    set_session("both")
    set_allow_expiry(False)

    print("\n--- BASELINE (full period, unchanged) ---", flush=True)
    base_full = metrics(run_bt(candles, lot, capital, base))
    base_train = metrics(run_bt(train, lot, capital, base))
    base_val = metrics(run_bt(val, lot, capital, base))
    base_oos = metrics(run_bt(oos, lot, capital, base))
    base_score = balanced_score(base_train, max(base_train["trades"], 1))
    print(json.dumps({"full": base_full, "train": base_train, "val": base_val, "oos": base_oos, "score_train": round(base_score, 2)}, indent=2), flush=True)

    rows: list[dict[str, Any]] = []

    def evaluate(label: str, group: str, ema: dict[str, Any], *, dataset="train", fast=9, slow=21, session="both", allow_expiry=False) -> dict[str, Any]:
        set_ema_pair(fast, slow)
        set_session(session)
        set_allow_expiry(allow_expiry)
        data = {"train": train, "val": val, "oos": oos, "full": candles}[dataset]
        result = run_bt(data, lot, capital, ema)
        m = metrics(result)
        ref_trades = max(base_train["trades"], 1) if dataset == "train" else max(base_full["trades"], 1)
        sc = balanced_score(m, ref_trades)
        row = {
            "label": label,
            "group": group,
            "dataset": dataset,
            "ema_fast": fast,
            "ema_slow": slow,
            "session": session,
            "params": {k: ema[k] for k in sorted(ema) if str(k).startswith("ema_")},
            "metrics": m,
            "score": round(sc, 2),
        }
        rows.append(row)
        print(
            f"{group:12} {label:28} [{dataset}] trades={m['trades']:>3} WR={m['win_rate']:>5}% "
            f"PF={m['profit_factor']:>5} EXP={m['expectancy']:>8} PnL={m['total_pnl']:>9} "
            f"DD={m['max_drawdown']:>8} score={sc:>6.1f}",
            flush=True,
        )
        return row

    # --- OFAT on TRAIN ---
    print("\n--- OFAT EMA pairs (train) ---", flush=True)
    for f, s in product(FAST_EMAS, SLOW_EMAS):
        if f >= s:
            continue
        evaluate(f"ema_{f}_{s}", "ema", deepcopy(base), fast=f, slow=s)

    print("\n--- OFAT lookback (train) ---", flush=True)
    set_ema_pair(9, 21)
    for lb in LOOKBACKS:
        orb = deepcopy(base)
        orb["ema_cross_lookback"] = lb
        evaluate(f"lb_{lb}", "lookback", orb)

    print("\n--- OFAT CALL RSI (train) ---", flush=True)
    for lo, hi in CALL_RSI:
        orb = deepcopy(base)
        orb.update({"ema_rsi_call_min": lo, "ema_rsi_call_max": hi})
        evaluate(f"call_{lo}_{hi}", "call_rsi", orb)

    print("\n--- OFAT PUT RSI (train) ---", flush=True)
    for lo, hi in PUT_RSI:
        orb = deepcopy(base)
        orb.update({"ema_rsi_put_min": lo, "ema_rsi_put_max": hi})
        evaluate(f"put_{lo}_{hi}", "put_rsi", orb)

    print("\n--- OFAT RSI slope (train) ---", flush=True)
    for flag in (False, True):
        orb = deepcopy(base)
        orb["ema_require_rsi_slope"] = flag
        evaluate(f"rsi_slope_{flag}", "rsi_slope", orb)

    print("\n--- OFAT VWAP (train) ---", flush=True)
    for flag in (False, True):
        orb = deepcopy(base)
        orb["ema_require_vwap"] = flag
        orb["ema_vwap_distance_pct"] = 0.0
        evaluate(f"vwap_{flag}", "vwap", orb)
    for dist in VWAP_DIST:
        orb = deepcopy(base)
        orb["ema_require_vwap"] = True
        orb["ema_vwap_distance_pct"] = dist
        evaluate(f"vwap_dist_{dist}", "vwap_dist", orb)

    print("\n--- OFAT momentum (train) ---", flush=True)
    for mode in ("off", "a", "b"):
        orb = deepcopy(base)
        orb["ema_require_two_bar_momentum"] = mode != "off"
        orb["ema_momentum_mode"] = mode
        evaluate(f"mom_{mode}", "momentum", orb)
    for atr_m in MOM_ATR:
        orb = deepcopy(base)
        orb["ema_require_two_bar_momentum"] = True
        orb["ema_momentum_mode"] = "c"
        orb["ema_momentum_atr"] = atr_m
        evaluate(f"mom_atr_{atr_m}", "momentum_atr", orb)

    print("\n--- OFAT volume (train) ---", flush=True)
    for v in VOL_RATIOS:
        orb = deepcopy(base)
        orb["ema_vol_min"] = float(v)
        orb["ema_use_vol_spike"] = False
        evaluate(f"vol_{v}", "volume", orb)

    print("\n--- OFAT EMA separation (train) ---", flush=True)
    for sep in SEP_PCTS:
        orb = deepcopy(base)
        orb["ema_min_separation_pct"] = float(sep)
        evaluate(f"sep_{sep}", "separation", orb)

    print("\n--- OFAT stop (train) ---", flush=True)
    for sl in STOPS:
        orb = deepcopy(base)
        orb["ema_stop_pts"] = float(sl)
        evaluate(f"sl_{sl}", "stop", orb)

    print("\n--- OFAT target (train) ---", flush=True)
    for tp in TARGETS:
        orb = deepcopy(base)
        orb["ema_target_pts"] = float(tp)
        evaluate(f"tp_{tp}", "target", orb)

    print("\n--- OFAT hold (train) ---", flush=True)
    for h in HOLDS:
        orb = deepcopy(base)
        orb["ema_max_hold_bars"] = int(h)
        evaluate(f"hold_{h}", "hold", orb)

    print("\n--- Session ablation (train) ---", flush=True)
    for sess in ("both", "morning", "afternoon"):
        evaluate(f"sess_{sess}", "session", deepcopy(base), session=sess)

    print("\n--- Expiry weekday (train, allow Wed) ---", flush=True)
    evaluate("allow_wed", "expiry", deepcopy(base), allow_expiry=True)

    def best_in_group(group: str) -> dict[str, Any] | None:
        g = [r for r in rows if r["group"] == group and r["dataset"] == "train" and r["metrics"]["trades"] >= MIN_TRADES]
        if not g:
            g = [r for r in rows if r["group"] == group and r["dataset"] == "train" and r["metrics"]["trades"] >= 3]
        if not g:
            return None
        return max(g, key=lambda r: r["score"])

    picks = {g: best_in_group(g) for g in [
        "ema", "lookback", "call_rsi", "put_rsi", "rsi_slope", "vwap", "vwap_dist",
        "momentum", "momentum_atr", "volume", "separation", "stop", "target", "hold", "session",
    ]}
    print("\n--- Best OFAT (train) ---", flush=True)
    for g, row in picks.items():
        if row:
            print(f"  {g}: {row['label']} score={row['score']} WR={row['metrics']['win_rate']} trades={row['metrics']['trades']}", flush=True)

    # SL/Target combos from top stops/targets
    print("\n--- SL/Target combos (train) ---", flush=True)
    stop_rows = sorted(
        [r for r in rows if r["group"] == "stop" and r["metrics"]["trades"] >= max(3, MIN_TRADES // 2)],
        key=lambda r: r["score"],
        reverse=True,
    )[:4]
    tgt_rows = sorted(
        [r for r in rows if r["group"] == "target" and r["metrics"]["trades"] >= max(3, MIN_TRADES // 2)],
        key=lambda r: r["score"],
        reverse=True,
    )[:4]
    for sr, tr in product(stop_rows or [None], tgt_rows or [None]):
        if not sr or not tr:
            continue
        orb = deepcopy(base)
        orb["ema_stop_pts"] = float(sr["params"]["ema_stop_pts"])
        orb["ema_target_pts"] = float(tr["params"]["ema_target_pts"])
        evaluate(f"rr_{int(orb['ema_stop_pts'])}_{int(orb['ema_target_pts'])}", "rr_combo", orb)

    # Refined combos
    print("\n--- Refined combos (train → val) ---", flush=True)
    fast_b, slow_b = 9, 21
    if picks["ema"]:
        fast_b, slow_b = int(picks["ema"]["ema_fast"]), int(picks["ema"]["ema_slow"])
    # Stability neighbours for EMA
    ema_candidates = sorted({(9, 21), (fast_b, slow_b), (max(5, fast_b - 1), slow_b), (fast_b, min(30, slow_b + 1)), (fast_b, max(fast_b + 1, slow_b - 1))})
    ema_candidates = [(f, s) for f, s in ema_candidates if f < s]

    def pget(group, key, default):
        row = picks.get(group)
        if not row:
            return default
        return row["params"].get(key, default)

    combo_specs: list[tuple[str, int, int, dict[str, Any]]] = []
    core = deepcopy(base)
    core.update(
        {
            "ema_cross_lookback": int(pget("lookback", "ema_cross_lookback", 3)),
            "ema_rsi_call_min": int(pget("call_rsi", "ema_rsi_call_min", 53)),
            "ema_rsi_call_max": int(pget("call_rsi", "ema_rsi_call_max", 60)),
            "ema_rsi_put_min": int(pget("put_rsi", "ema_rsi_put_min", 40)),
            "ema_rsi_put_max": int(pget("put_rsi", "ema_rsi_put_max", 46)),
            "ema_require_vwap": bool(pget("vwap", "ema_require_vwap", True)),
            "ema_vwap_distance_pct": float(pget("vwap_dist", "ema_vwap_distance_pct", 0.0)) if picks.get("vwap_dist") and picks["vwap_dist"]["score"] > base_score else 0.0,
            "ema_require_rsi_slope": bool(pget("rsi_slope", "ema_require_rsi_slope", False)) if picks.get("rsi_slope") and picks["rsi_slope"]["params"].get("ema_require_rsi_slope") and picks["rsi_slope"]["score"] > base_score + 5 else False,
            "ema_vol_min": float(pget("volume", "ema_vol_min", 0.0)),
            "ema_min_separation_pct": float(pget("separation", "ema_min_separation_pct", 0.0)),
            "ema_stop_pts": float(pget("stop", "ema_stop_pts", 65)),
            "ema_target_pts": float(pget("target", "ema_target_pts", 130)),
            "ema_max_hold_bars": int(pget("hold", "ema_max_hold_bars", 8)),
            "ema_require_two_bar_momentum": True,
            "ema_momentum_mode": "a",
        }
    )
    # Don't enable volume/sep if OFAT winner is essentially OFF or score barely better
    if float(core["ema_vol_min"] or 0) > 0 and picks.get("volume") and picks["volume"]["score"] < base_score + 3:
        core["ema_vol_min"] = 0.0
    if float(core["ema_min_separation_pct"] or 0) > 0 and picks.get("separation") and picks["separation"]["score"] < base_score + 3:
        core["ema_min_separation_pct"] = 0.0

    for f, s in ema_candidates:
        combo_specs.append((f"core_{f}_{s}", f, s, deepcopy(core)))

    # Also keep baseline + best single changes
    combo_specs.append(("baseline_ref", 9, 21, deepcopy(base)))
    if picks.get("call_rsi"):
        orb = deepcopy(base)
        orb.update({k: picks["call_rsi"]["params"][k] for k in ("ema_rsi_call_min", "ema_rsi_call_max")})
        combo_specs.append(("call_only", 9, 21, orb))
    if picks.get("lookback"):
        orb = deepcopy(base)
        orb["ema_cross_lookback"] = picks["lookback"]["params"]["ema_cross_lookback"]
        combo_specs.append(("lb_only", 9, 21, orb))

    # Top rr combo merge into core
    rr_best = best_in_group("rr_combo")
    if rr_best:
        orb = deepcopy(core)
        orb["ema_stop_pts"] = rr_best["params"]["ema_stop_pts"]
        orb["ema_target_pts"] = rr_best["params"]["ema_target_pts"]
        combo_specs.append(("core_rr", fast_b, slow_b, orb))

    seen = set()
    unique_specs = []
    for name, f, s, ema in combo_specs:
        key = json.dumps({"f": f, "s": s, **ema}, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        unique_specs.append((name, f, s, ema))

    print(f"combo count={len(unique_specs)}", flush=True)
    combo_train_rows = []
    for name, f, s, ema in unique_specs:
        row = evaluate(name, "combo", ema, fast=f, slow=s, dataset="train")
        combo_train_rows.append(row)

    # Validate top train combos on VAL
    print("\n--- Validation ---", flush=True)
    top_train = sorted(
        [r for r in combo_train_rows if r["metrics"]["trades"] >= max(3, MIN_TRADES // 2)],
        key=lambda r: r["score"],
        reverse=True,
    )[:8]
    if not top_train:
        top_train = sorted(combo_train_rows, key=lambda r: r["score"], reverse=True)[:5]

    val_rows = []
    for tr in top_train:
        row = evaluate(
            tr["label"] + "_val",
            "combo_val",
            tr["params"],
            dataset="val",
            fast=tr["ema_fast"],
            slow=tr["ema_slow"],
        )
        val_rows.append({**row, "train_score": tr["score"], "train_metrics": tr["metrics"]})

    def pick_recommended(val_rows_local):
        if not val_rows_local:
            return None
        # Prefer val score, require positive expectancy on val if trades>=3
        eligible = [
            r
            for r in val_rows_local
            if r["metrics"]["expectancy"] > 0 or r["metrics"]["trades"] < 3
        ]
        pool = eligible or val_rows_local
        # Among top val scores within 8 pts, prefer higher train stability / more trades
        pool = sorted(pool, key=lambda r: r["score"], reverse=True)
        top = pool[0]["score"]
        near = [r for r in pool if r["score"] >= top - 8]
        return max(near, key=lambda r: (r["score"], r["metrics"]["trades"], r.get("train_score", 0)))

    recommended_val = pick_recommended(val_rows)

    print("\n--- Out-of-sample ---", flush=True)
    rec_full = rec_oos = None
    if recommended_val:
        rec_oos = evaluate(
            "recommended_oos",
            "oos",
            recommended_val["params"],
            dataset="oos",
            fast=recommended_val["ema_fast"],
            slow=recommended_val["ema_slow"],
        )
        rec_full = evaluate(
            "recommended_full",
            "full",
            recommended_val["params"],
            dataset="full",
            fast=recommended_val["ema_fast"],
            slow=recommended_val["ema_slow"],
        )

    # Loss quality on baseline full
    print("\n--- Loss trade quality (baseline full) ---", flush=True)
    set_ema_pair(9, 21)
    set_session("both")
    set_allow_expiry(False)
    base_result = run_bt(candles, lot, capital, base)
    losses = [t for t in (base_result.get("trades") or []) if float(t.get("pnl") or 0) <= 0]
    afternoon_losses = 0
    for t in losses:
        hhmm = _hhmm(str(t.get("entry_time") or ""))
        if hhmm and 13 * 60 + 30 <= hhmm <= 14 * 60 + 45:
            afternoon_losses += 1
    loss_quality = {
        "losing_trades": len(losses),
        "afternoon_losses": afternoon_losses,
        "morning_losses": len(losses) - afternoon_losses,
        "note": "Detailed bar-level MAE/+0.5R requires entry-path instrumentation; summarized by session here.",
    }
    print(json.dumps(loss_quality, indent=2), flush=True)

    # Rank all train eligible
    eligible_train = [r for r in rows if r["dataset"] == "train" and r["metrics"]["trades"] >= MIN_TRADES]
    ranked = sorted(eligible_train, key=lambda r: r["score"], reverse=True)

    report = {
        "strategy": STRATEGY_CODE,
        "instrument": INSTRUMENT_KEY,
        "data_source": source,
        "date_range": {"from": from_date, "to": to_date},
        "bars": len(candles),
        "walk_forward": {"train": len(train), "val": len(val), "oos": len(oos)},
        "baseline": {
            "params": base,
            "ema_pair": [9, 21],
            "full": base_full,
            "train": base_train,
            "val": base_val,
            "oos": base_oos,
        },
        "ofat_best": {k: (v and {"label": v["label"], "score": v["score"], "metrics": v["metrics"], "params": v["params"], "ema": [v["ema_fast"], v["ema_slow"]]}) for k, v in picks.items()},
        "top10_train": ranked[:10],
        "validation": val_rows,
        "recommended": recommended_val,
        "recommended_oos": rec_oos,
        "recommended_full": rec_full,
        "loss_quality": loss_quality,
        "notes": [
            "EMA pairs tested by recomputing ema9/ema21 columns as fast/slow spans (opt patch only).",
            "Volume/separation OFAT used run_backtest directly (avoids run_strategy_backtest reset).",
            "RSI slope, VWAP distance, momentum modes B/C are opt-only extras; promote only if kept in recommendation.",
            "Walk-forward: 60% train / 20% val / 20% oos by bar order.",
        ],
    }

    out_path = os.environ.get("REPORT_PATH", "/tmp/optimize_scalp_bt003_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nWrote report → {out_path}", flush=True)

    print("\n=== TOP 10 TRAIN ===", flush=True)
    for i, r in enumerate(ranked[:10], 1):
        m = r["metrics"]
        print(
            f"{i:2}. [{r['group']}] {r['label']} EMA{r['ema_fast']}/{r['ema_slow']} "
            f"score={r['score']} WR={m['win_rate']}% PF={m['profit_factor']} "
            f"trades={m['trades']} PnL={m['total_pnl']} DD={m['max_drawdown']}",
            flush=True,
        )

    if recommended_val:
        print("\n=== RECOMMENDED (selected on validation) ===", flush=True)
        print(
            json.dumps(
                {
                    "label": recommended_val["label"],
                    "ema": [recommended_val["ema_fast"], recommended_val["ema_slow"]],
                    "params": recommended_val["params"],
                    "val_metrics": recommended_val["metrics"],
                    "oos_metrics": rec_oos["metrics"] if rec_oos else None,
                    "full_metrics": rec_full["metrics"] if rec_full else None,
                },
                indent=2,
            ),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
