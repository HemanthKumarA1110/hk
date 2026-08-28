#!/usr/bin/env python3
"""Final metrics dump for recommended SCALP-BT-004 params."""
from __future__ import annotations

import json
import pickle
from copy import deepcopy

from trading_shared.strategies.scalping_desk.backtest import run_strategy_backtest
from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS
from trading_shared.strategies.scalping_desk.orb_breakout_tuning import ORB_BREAKOUT_NIFTY_DEFAULTS

# Recommended (robust WR-primary, momentum retained via ATR)
REC = {
    "orb_minutes": 15,
    "orb_entry_cutoff_min": 14 * 60 + 45,
    "orb_buffer_pct": 1.66e-4,  # ~4 pts @ Nifty ~24.1k
    "orb_vol_min": 1.15,
    "orb_use_vol_spike": False,
    "orb_rsi_call_min": 52,
    "orb_rsi_call_max": 66,
    "orb_rsi_put_min": 32,
    "orb_rsi_put_max": 46,
    "orb_require_inside_or": False,
    "orb_prior_mode": "off",
    "orb_require_two_bar_momentum": True,
    "orb_momentum_mode": "atr",
    "orb_momentum_atr_mult": 0.25,
    "orb_ema_fast": 8,
    "orb_ema_slow": 20,
    "orb_min_separation_pct": 0.0,
    "orb_vol_lookback": 0,
    "orb_require_rsi_slope": False,
    "orb_min_body_pct": 0.0,
    "orb_require_vwap": False,
    "orb_or_range_min": 45.0,
    "orb_or_range_max": 80.0,
    "orb_stop_pts": 6.0,
    "orb_target_pts": 12.0,
    "orb_max_hold_bars": 10,
    "orb_skip_wide_or": True,
}

# Alt high-PF candidate (mom off) for report comparison
ALT = deepcopy(REC)
ALT.update({
    "orb_require_two_bar_momentum": False,
    "orb_momentum_mode": "two_bar",
    "orb_momentum_atr_mult": 0.0,
    "orb_vol_min": 1.35,
    "orb_buffer_pct": 1.66e-4,
})


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


def enrich(res, candles):
    trades = res.get("trades") or []
    n = int(res["total_trades"])
    pnl = float(res["total_pnl"])
    mw, ml = streaks(trades)
    wins = [t for t in trades if float(t.get("pnl") or 0) > 0]
    losses = [t for t in trades if float(t.get("pnl") or 0) <= 0]
    calls = [t for t in trades if str(t.get("signal_type")).upper() == "CALL"]
    puts = [t for t in trades if str(t.get("signal_type")).upper() == "PUT"]
    morning, afternoon = [], []

    def hhmm(ts):
        try:
            part = ts.split("T")[1][:5] if "T" in ts else ts.split(" ")[1][:5]
            h, m = part.split(":")
            return int(h) * 60 + int(m)
        except Exception:
            return None

    buckets = {k: [] for k in (
        "09:20-09:30", "09:30-09:45", "09:45-10:00", "10:00-10:15", "10:15-10:30",
        "13:30-14:00", "14:00-14:30", "14:30-14:45",
    )}
    for t in trades:
        m = hhmm(str(t.get("entry_time") or ""))
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

    regimes = {}
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
        "win_rate": float(res["win_rate"]),
        "profit_factor": float(res["profit_factor"]),
        "expectancy": round(pnl / n, 2) if n else 0.0,
        "total_pnl": pnl,
        "max_drawdown": float(res["max_drawdown"]),
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
        "loss_exits": {},
    }


with open("/tmp/bt004_candles.pkl", "rb") as f:
    payload = pickle.load(f)
df = payload["df"]
lot = int(INSTRUMENTS["nifty50"]["lot_size"])
n = len(df)
train, val, oos = df.iloc[: int(n * 0.6)], df.iloc[int(n * 0.6) : int(n * 0.8)], df.iloc[int(n * 0.8) :]


def bt(orb, frame):
    return run_strategy_backtest(
        frame.reset_index(drop=True), "1m", lot, 100000,
        strategy_code="SCALP-BT-004", instrument_key="nifty50",
        params={"orb_breakout": orb}, max_loss_per_day=5000, max_trades_per_day=5,
    )


base = dict(ORB_BREAKOUT_NIFTY_DEFAULTS)
out = {
    "data": {"bars": len(df), "from": payload["from_date"], "to": payload["to_date"], "source": payload["source"]},
    "baseline_full": enrich(bt(base, df), df),
    "recommended_params": REC,
    "recommended": {
        "train": enrich(bt(REC, train), train.reset_index(drop=True)),
        "val": enrich(bt(REC, val), val.reset_index(drop=True)),
        "oos": enrich(bt(REC, oos), oos.reset_index(drop=True)),
        "full": enrich(bt(REC, df), df),
    },
    "alt_vol135_mom_off": {
        "params": ALT,
        "full": enrich(bt(ALT, df), df),
    },
}
# loss exits
full_res = bt(REC, df)
for t in full_res.get("trades") or []:
    if float(t.get("pnl") or 0) <= 0:
        reason = str(t.get("exit_reason") or "?")
        out["recommended"]["full"]["loss_exits"][reason] = out["recommended"]["full"]["loss_exits"].get(reason, 0) + 1

with open("/tmp/bt004_final_metrics.json", "w") as f:
    json.dump(out, f, indent=2, default=str)
print(json.dumps({
    "baseline": out["baseline_full"],
    "rec_full": out["recommended"]["full"],
    "rec_train": {k: out["recommended"]["train"][k] for k in ("trades", "win_rate", "profit_factor", "expectancy", "total_pnl", "max_drawdown")},
    "rec_val": {k: out["recommended"]["val"][k] for k in ("trades", "win_rate", "profit_factor", "expectancy", "total_pnl", "max_drawdown")},
    "rec_oos": {k: out["recommended"]["oos"][k] for k in ("trades", "win_rate", "profit_factor", "expectancy", "total_pnl", "max_drawdown")},
    "alt_full": out["alt_vol135_mom_off"]["full"],
}, indent=2, default=str), flush=True)
