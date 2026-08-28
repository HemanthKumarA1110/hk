"""
Battle-tested intraday scalping rules (EMA + RSI / ORB).

Tuned from backtest benchmarks:
  Nifty 50  — EMA crossover + RSI
  Bank Nifty — EMA crossover + RSI (consistency) or ORB breakout (P&L)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from trading_shared.strategies.scalping_desk.engine import (
    ScalpSignal,
    enrich_candles,
    long_premium_brackets,
    max_hold_bars,
    pick_strike,
    premium_risk_from_index,
)
from trading_shared.strategies.scalping_desk.strategies import _two_bar_momentum
from trading_shared.strategies.scalping_desk.orb_breakout_tuning import merge_orb_params
from trading_shared.strategies.scalping_desk.ema_crossover_tuning import merge_ema_crossover_params
from trading_shared.strategies.ta import ema

IST = ZoneInfo("Asia/Kolkata")

# Session: fixed battle-tested windows (IST).
SESSION_WINDOWS = ((9, 20, 10, 30), (13, 30, 14, 45))
SESSION_WINDOW_LABELS = ("09:20–10:30", "13:30–14:45")
MARKET_OPEN = (9, 15)
MARKET_CLOSE = (15, 30)
SKIP_OPEN_MINUTES = 5
SKIP_CLOSE_MINUTES = 15

EXPIRY_WEEKDAY: dict[str, int] = {
    "nifty50": 3,  # Thursday weekly (2026+)
    "banknifty": 2,  # Wednesday weekly
}

BATTLE_RISK: dict[str, dict[str, float | int]] = {
    "nifty50": {
        "stop_pts": 6.0,
        "target_pts": 12.0,
        "max_hold_bars": 10,
        "orb_minutes": 15,
    },
    "banknifty": {
        "stop_pts": 65.0,
        "target_pts": 130.0,
        "max_hold_bars": 8,
        "orb_minutes": 15,
    },
}


def _to_ist(ts: Any) -> datetime | None:
    dt = pd.to_datetime(ts, errors="coerce")
    if pd.isna(dt):
        return None
    if dt.tzinfo is None:
        return dt.to_pydatetime().replace(tzinfo=IST)
    return dt.astimezone(IST)


def _active_battle_window(ts: Any) -> str | None:
    ist = _to_ist(ts)
    if ist is None or ist.weekday() >= 5:
        return None
    minutes = ist.hour * 60 + ist.minute
    for (h1, m1, h2, m2), label in zip(SESSION_WINDOWS, SESSION_WINDOW_LABELS, strict=True):
        if (h1 * 60 + m1) <= minutes < (h2 * 60 + m2):
            return label
    return None


def _resolve_live_session_ts(ts: Any) -> Any:
    """Use wall clock only for same-day stream lag — never for historical/backtest bars."""
    parsed = _to_ist(ts)
    now = datetime.now(IST)
    if parsed is None:
        return now
    age_sec = (now - parsed).total_seconds()
    if parsed.date() == now.date() and 90 < age_sec <= 8 * 3600:
        return now
    return ts


def in_battle_session(
    ts: Any = None,
    *,
    df: pd.DataFrame | None = None,
    instrument_key: str = "nifty50",
    tick: dict[str, Any] | None = None,
    mtf_context: dict[str, Any] | None = None,
    macro_inputs: dict[str, Any] | None = None,
    signal_type: str | None = None,
) -> bool:
    """Fixed battle windows: 09:20–10:30 and 13:30–14:45 IST (Mon–Fri)."""
    if ts is None and df is not None and len(df):
        ts = df.iloc[-1].get("timestamp")
    ts = _resolve_live_session_ts(ts)
    return _active_battle_window(ts) is not None


def evaluate_battle_session(
    ts: Any = None,
    *,
    instrument_key: str = "nifty50",
) -> dict[str, Any]:
    """Structured session status for desk UI and market context."""
    active = _active_battle_window(ts)
    ok = active is not None
    ist = _to_ist(ts)
    return {
        "session_ok": ok,
        "mode": "battle_windows",
        "windows": list(SESSION_WINDOW_LABELS),
        "active_window": active,
        "checks": {
            "battle_window": {
                "ok": ok,
                "detail": f"inside {active} IST" if ok else "outside 09:20–10:30 / 13:30–14:45 IST",
            }
        },
        "failed": [] if ok else ["battle_window"],
        "summary": f"battle window {active}" if ok else "outside battle windows (09:20–10:30 / 13:30–14:45 IST)",
        "evaluated_at": ist.isoformat() if ist else None,
        "instrument_key": instrument_key,
    }


def precompute_battle_session_mask(
    data: pd.DataFrame,
    instrument_key: str = "nifty50",
) -> list[bool]:
    """Fast per-bar mask for backtest replay."""
    if data is None or data.empty:
        return []
    return [_active_battle_window(row.get("timestamp")) is not None for _, row in data.iterrows()]


def is_expiry_day(ts: Any, instrument_key: str) -> bool:
    from trading_shared.strategies.scalping_desk.expiry_day_handler import is_instrument_expiry_day

    return is_instrument_expiry_day(ts, instrument_key)


def _expiry_blocks_entry(ts: Any, instrument_key: str) -> bool:
    from trading_shared.strategies.scalping_desk.expiry_day_handler import (
        expiry_blocks_new_entries,
        handle_expiry_day,
    )

    return expiry_blocks_new_entries(handle_expiry_day(instrument_key, ts))


def _recent_cross(data: pd.DataFrame, direction: str, lookback: int = 3) -> bool:
    """Fresh EMA cross within the last few bars (not open-ended trend continuation)."""
    if len(data) < lookback + 2:
        return False
    tail = data.tail(lookback + 1)
    for i in range(1, len(tail)):
        if direction == "CALL":
            if tail["ema9"].iloc[i] > tail["ema21"].iloc[i] and tail["ema9"].iloc[i - 1] <= tail["ema21"].iloc[i - 1]:
                return True
        elif tail["ema9"].iloc[i] < tail["ema21"].iloc[i] and tail["ema9"].iloc[i - 1] >= tail["ema21"].iloc[i - 1]:
            return True
    return False


def battle_risk(instrument_key: str) -> dict[str, float | int]:
    return dict(BATTLE_RISK.get(instrument_key, BATTLE_RISK["nifty50"]))


def _session_orb(df: pd.DataFrame, orb_minutes: int = 15) -> dict[str, float] | None:
    if "timestamp" not in df.columns or df.empty:
        return None
    frame = df.copy()
    frame["ts"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame = frame.dropna(subset=["ts"])
    if frame.empty:
        return None
    day = frame["ts"].iloc[-1].date()
    day_rows = frame.loc[frame["ts"].dt.date == day]
    # ORB starts after 5-min skip (09:20 IST)
    tradable = day_rows[day_rows["ts"].dt.hour * 60 + day_rows["ts"].dt.minute >= 9 * 60 + 20]
    segment = tradable.head(orb_minutes)
    if len(segment) < max(5, orb_minutes // 2):
        return None
    hi = float(segment["high"].max())
    lo = float(segment["low"].min())
    return {"high": hi, "low": lo, "mid": (hi + lo) / 2}


def _build_battle_signal(
    *,
    strategy_id: str,
    strategy_label: str,
    signal_type: str,
    data: pd.DataFrame,
    timeframe: str,
    option_chain: dict[str, Any],
    instrument_key: str,
    conditions: list[str],
    risk: dict[str, float | int],
) -> ScalpSignal | None:
    row = data.iloc[-1]
    spot = float(row["close"])
    strike_info = pick_strike(option_chain, spot, signal_type)
    if not strike_info:
        return None

    stop_pts = float(risk["stop_pts"])
    target_pts = float(risk["target_pts"])
    hold = int(risk.get("max_hold_bars") or max_hold_bars(instrument_key))

    option_ltp = float(strike_info.get("ltp") or strike_info.get("premium") or 1)
    sl_points, target_points = premium_risk_from_index(option_ltp, stop_pts, target_pts)
    entry = option_ltp
    stoploss, target = long_premium_brackets(entry, sl_points, target_points)

    ts = row.get("timestamp")
    now_iso = _to_ist(ts).isoformat() if _to_ist(ts) else datetime.now(IST).isoformat()

    indicators = {
        "ema9": round(float(row["ema9"]), 2),
        "ema21": round(float(row["ema21"]), 2),
        "rsi": round(float(row["rsi14"]), 2),
        "vwap": round(float(row.get("vwap", spot)), 2),
        "atr": round(float(row.get("atr") or spot * 0.002), 2),
        "spot": round(spot, 2),
        "index_stop_pts": stop_pts,
        "index_target_pts": target_pts,
        "max_hold_bars": hold,
        "strategy_id": strategy_id,
        "use_fixed_risk": True,
        "risk_reward": round(target_pts / max(stop_pts, 0.01), 2),
    }

    return ScalpSignal(
        signal_type=signal_type,
        strike=float(strike_info["strike"]),
        option_symbol=str(strike_info["symbol"]),
        option_token=str(strike_info.get("token") or ""),
        entry=round(entry, 2),
        target=target,
        stoploss=stoploss,
        timeframe=timeframe,
        indicators=indicators,
        conditions_met=conditions + [strategy_id],
        timestamp=now_iso,
    )


def evaluate_ema_crossover_rsi(
    df: pd.DataFrame,
    timeframe: str,
    option_chain: dict[str, Any],
    lot_size: int,
    *,
    enriched: bool = False,
    instrument_key: str = "nifty50",
    params: dict[str, Any] | None = None,
    skip_session: bool = False,
) -> ScalpSignal | None:
    """EMA 9/21 crossover confirmed by RSI — primary Nifty & BankNifty setup."""
    if len(df) < 25:
        return None

    p = merge_ema_crossover_params(params, instrument_key)
    data = df if enriched else enrich_candles(df)
    fast = int(p.get("ema_fast") or 9)
    slow = int(p.get("ema_slow") or 21)
    if fast != 9 or slow != 21:
        data = data.copy()
        data["ema9"] = ema(data["close"], fast)
        data["ema21"] = ema(data["close"], slow)
    row = data.iloc[-1]
    ts = row.get("timestamp")

    if not skip_session and not in_battle_session(ts, df=data, instrument_key=instrument_key):
        return None
    if _expiry_blocks_entry(ts, instrument_key):
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

    call_ok = (
        _recent_cross(data, "CALL", lookback=lookback)
        and ema9 > ema21
        and call_rsi_min <= rsi_val <= call_rsi_max
        and (not need_vwap or spot > vwap)
        and (not need_momentum or _two_bar_momentum(data, "CALL"))
    )
    put_ok = (
        _recent_cross(data, "PUT", lookback=lookback)
        and ema9 < ema21
        and put_rsi_min <= rsi_val <= put_rsi_max
        and (not need_vwap or spot < vwap)
        and (not need_momentum or _two_bar_momentum(data, "PUT"))
    )

    if not call_ok and not put_ok:
        return None

    signal_type = "CALL" if call_ok else "PUT"
    risk = battle_risk(instrument_key)
    risk = {
        **risk,
        "stop_pts": float(p.get("ema_stop_pts") or risk["stop_pts"]),
        "target_pts": float(p.get("ema_target_pts") or risk["target_pts"]),
        "max_hold_bars": int(p.get("ema_max_hold_bars") or risk["max_hold_bars"]),
    }
    return _build_battle_signal(
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


def evaluate_orb_breakout(
    df: pd.DataFrame,
    timeframe: str,
    option_chain: dict[str, Any],
    lot_size: int,
    *,
    enriched: bool = False,
    instrument_key: str = "banknifty",
    params: dict[str, Any] | None = None,
    skip_session: bool = False,
) -> ScalpSignal | None:
    """Opening-range breakout — Nifty / Bank Nifty battle setup."""
    if len(df) < 30:
        return None

    p = merge_orb_params(params, instrument_key)
    data = df if enriched else enrich_candles(df)
    fast = int(p.get("orb_ema_fast") or 9)
    slow = int(p.get("orb_ema_slow") or 21)
    if fast != 9 or slow != 21:
        data = data.copy()
        data["ema9"] = ema(data["close"], fast)
        data["ema21"] = ema(data["close"], slow)

    vol_lb = int(p.get("orb_vol_lookback") or 0)
    if vol_lb > 0 and len(data) >= vol_lb:
        data = data.copy()
        activity = data["volume"] if float(data["volume"].sum() or 0) > 0 else (data["high"] - data["low"]).abs()
        avg = activity.rolling(vol_lb, min_periods=max(3, vol_lb // 3)).mean().replace(0, 1)
        data["volume_ratio"] = activity / avg

    row = data.iloc[-1]
    prev = data.iloc[-2]
    ts = row.get("timestamp")

    if not skip_session and not in_battle_session(ts, df=data, instrument_key=instrument_key):
        return None
    if _expiry_blocks_entry(ts, instrument_key):
        return None

    ist = _to_ist(ts)
    if ist is None:
        return None
    minutes = ist.hour * 60 + ist.minute
    entry_cutoff = int(p.get("orb_entry_cutoff_min") or (10 * 60 + 30))
    if minutes > entry_cutoff:
        return None

    risk = battle_risk(instrument_key)
    risk = {
        **risk,
        "stop_pts": float(p.get("orb_stop_pts") or risk["stop_pts"]),
        "target_pts": float(p.get("orb_target_pts") or risk["target_pts"]),
        "max_hold_bars": int(p.get("orb_max_hold_bars") or risk["max_hold_bars"]),
        "orb_minutes": int(p.get("orb_minutes") or risk.get("orb_minutes") or 15),
    }

    orb = _session_orb(data, int(risk.get("orb_minutes", 15)))
    if not orb:
        return None

    or_range = float(orb["high"] - orb["low"])
    rmin = float(p.get("orb_or_range_min") or 0)
    rmax = float(p.get("orb_or_range_max") or 99999)
    if or_range < rmin:
        return None
    if p.get("orb_skip_wide_or") and or_range > rmax:
        return None

    spot = float(row["close"])
    prev_close = float(prev["close"])
    prev_high = float(prev["high"])
    prev_low = float(prev["low"])
    ema9 = float(row["ema9"])
    ema21 = float(row["ema21"])
    rsi_val = float(row["rsi14"])
    prev_rsi = float(prev["rsi14"])
    vol_ratio = float(row.get("volume_ratio") or 0)
    vol_spike = bool(row.get("vol_spike"))
    vwap = float(row.get("vwap", spot))
    atr = float(row.get("atr") or 0) or max(spot * 0.0004, 1.0)

    sep_pct = float(p.get("orb_min_separation_pct") or 0)
    if sep_pct > 0 and abs(ema9 - ema21) / max(spot, 1) * 100 < sep_pct:
        return None

    buffer = spot * float(p.get("orb_buffer_pct") or 0.0003)
    vol_min = float(p.get("orb_vol_min") or 1.35)
    use_vol_spike = bool(p.get("orb_use_vol_spike", False))
    vol_ok = vol_ratio >= vol_min or (use_vol_spike and vol_spike)

    prior_mode = str(p.get("orb_prior_mode") or "").lower().strip()
    if not prior_mode:
        prior_mode = "close_inside" if bool(p.get("orb_require_inside_or", True)) else "off"

    if prior_mode in ("inside", "a", "complete"):
        if not (orb["low"] <= prev_low and prev_high <= orb["high"]):
            return None
    elif prior_mode in ("close_inside", "b", "close"):
        if not (orb["low"] <= prev_close <= orb["high"]):
            return None
    elif prior_mode in ("not_beyond", "c", "off", "d", "none"):
        pass
    else:
        if not (orb["low"] <= prev_close <= orb["high"]):
            return None

    call_rsi_min = int(p.get("orb_rsi_call_min") or 50)
    call_rsi_max = int(p.get("orb_rsi_call_max") or 65)
    put_rsi_min = int(p.get("orb_rsi_put_min") or 34)
    put_rsi_max = int(p.get("orb_rsi_put_max") or 48)
    need_momentum = bool(p.get("orb_require_two_bar_momentum", True))
    mom_mode = str(p.get("orb_momentum_mode") or "two_bar").lower()
    mom_atr = float(p.get("orb_momentum_atr_mult") or 0)
    need_vwap = bool(p.get("orb_require_vwap", False))
    need_rsi_slope = bool(p.get("orb_require_rsi_slope", False))
    min_body = float(p.get("orb_min_body_pct") or 0)

    def _body_ok(direction: str) -> bool:
        if min_body <= 0:
            return True
        hi, lo, op, cl = float(row["high"]), float(row["low"]), float(row["open"]), float(row["close"])
        rng = max(hi - lo, 1e-9)
        body = abs(cl - op) / rng
        if body < min_body:
            return False
        return (cl > op) if direction == "CALL" else (cl < op)

    def _momentum_ok(direction: str) -> bool:
        if not need_momentum:
            return True
        if mom_mode in ("directional", "closes", "b"):
            c0 = float(data.iloc[-1]["close"])
            c1 = float(data.iloc[-2]["close"])
            c2 = float(data.iloc[-3]["close"]) if len(data) >= 3 else c1
            return (c0 > c1 > c2) if direction == "CALL" else (c0 < c1 < c2)
        if mom_mode in ("atr", "c") and mom_atr > 0 and len(data) >= 3:
            move = abs(float(data.iloc[-1]["close"]) - float(data.iloc[-3]["close"]))
            return move >= mom_atr * atr
        return _two_bar_momentum(data, direction)

    call_prior_ok = True
    put_prior_ok = True
    if prior_mode in ("not_beyond", "c"):
        call_prior_ok = prev_close <= orb["high"] + buffer
        put_prior_ok = prev_close >= orb["low"] - buffer

    call_ok = (
        call_prior_ok
        and spot > orb["high"] + buffer
        and ema9 > ema21
        and call_rsi_min <= rsi_val <= call_rsi_max
        and vol_ok
        and float(row["close"]) > float(row["open"])
        and _body_ok("CALL")
        and _momentum_ok("CALL")
        and (not need_vwap or spot > vwap)
        and (not need_rsi_slope or rsi_val > prev_rsi)
    )
    put_ok = (
        put_prior_ok
        and spot < orb["low"] - buffer
        and ema9 < ema21
        and put_rsi_min <= rsi_val <= put_rsi_max
        and vol_ok
        and float(row["close"]) < float(row["open"])
        and _body_ok("PUT")
        and _momentum_ok("PUT")
        and (not need_vwap or spot < vwap)
        and (not need_rsi_slope or rsi_val < prev_rsi)
    )
    if not call_ok and not put_ok:
        return None

    signal_type = "CALL" if call_ok else "PUT"
    return _build_battle_signal(
        strategy_id="orb_breakout",
        strategy_label="ORB Breakout",
        signal_type=signal_type,
        data=data,
        timeframe=timeframe,
        option_chain=option_chain,
        instrument_key=instrument_key,
        conditions=["orb_breakout", "ema_confirm", "battle_session"],
        risk=risk,
    )


BATTLE_REGISTRY: dict[str, dict[str, Any]] = {
    "ema_crossover_rsi": {
        "id": "ema_crossover_rsi",
        "label": "EMA Crossover + RSI",
        "description": "Best Nifty/BankNifty consistency — 1:2 RRR, session-filtered",
        "evaluate": evaluate_ema_crossover_rsi,
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "RANGING"],
        "instruments": ["nifty50", "banknifty"],
    },
    "orb_breakout": {
        "id": "orb_breakout",
        "label": "ORB Breakout",
        "description": "Opening-range breakout — Nifty / Bank Nifty battle setup",
        "evaluate": evaluate_orb_breakout,
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"],
        "instruments": ["nifty50", "banknifty"],
    },
}


def list_battle_strategies(instrument_key: str | None = None) -> list[dict[str, Any]]:
    out = []
    for meta in BATTLE_REGISTRY.values():
        if instrument_key and instrument_key not in meta.get("instruments", []):
            continue
        out.append(
            {
                "id": meta["id"],
                "label": meta["label"],
                "description": meta["description"],
                "best_regimes": meta["best_regimes"],
            }
        )
    return out


def evaluate_battle_best(
    df: pd.DataFrame,
    timeframe: str,
    option_chain: dict[str, Any],
    lot_size: int,
    instrument_key: str,
    *,
    params: dict[str, Any] | None = None,
    fixed_strategy_id: str | None = None,
    skip_session: bool = False,
    enriched: bool = False,
) -> tuple[ScalpSignal | None, dict[str, Any]]:
    """Pick battle-tested strategy for instrument."""
    if instrument_key == "banknifty" and fixed_strategy_id is None:
        order = ["ema_crossover_rsi", "orb_breakout"]
    elif fixed_strategy_id:
        order = [fixed_strategy_id]
    elif instrument_key == "nifty50":
        order = ["orb_breakout"]
    else:
        order = []

    meta = {
        "strategy_family": "battle",
        "mode": "auto" if not fixed_strategy_id else "manual",
        "selected_strategy": None,
        "selection_reason": "",
        "rankings": list_battle_strategies(instrument_key),
    }
    kwargs = {
        "enriched": enriched,
        "instrument_key": instrument_key,
        "params": params,
        "skip_session": skip_session,
    }
    for sid in order:
        reg = BATTLE_REGISTRY.get(sid)
        if not reg or instrument_key not in reg.get("instruments", []):
            continue
        signal = reg["evaluate"](df, timeframe, option_chain, lot_size, **kwargs)
        if signal:
            meta["selected_strategy"] = sid
            meta["selected_label"] = reg["label"]
            meta["selection_reason"] = reg["description"]
            return signal, meta
    meta["selected_strategy"] = order[0] if order else None
    return None, meta
