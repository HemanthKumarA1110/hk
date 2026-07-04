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
    max_hold_bars,
    pick_strike,
    premium_risk_from_index,
)
from trading_shared.strategies.scalping_desk.strategies import _two_bar_momentum

IST = ZoneInfo("Asia/Kolkata")

# Session: 09:20–10:30 and 13:30–14:45; skip 09:15–09:19 and after 15:15
SESSION_WINDOWS = ((9, 20, 10, 30), (13, 30, 14, 45))
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


def in_battle_session(ts: Any = None) -> bool:
    """Trade only in approved IST windows; skip open/close buffers."""
    now = _to_ist(ts) if ts is not None else datetime.now(IST)
    if now is None:
        return False
    minutes = now.hour * 60 + now.minute
    open_min = MARKET_OPEN[0] * 60 + MARKET_OPEN[1] + SKIP_OPEN_MINUTES
    close_cutoff = MARKET_CLOSE[0] * 60 + MARKET_CLOSE[1] - SKIP_CLOSE_MINUTES
    if minutes < open_min or minutes >= close_cutoff:
        return False
    for h1, m1, h2, m2 in SESSION_WINDOWS:
        if h1 * 60 + m1 <= minutes <= h2 * 60 + m2:
            return True
    return False


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

    if signal_type == "CALL":
        entry = option_ltp
        stoploss = round(entry - sl_points, 2)
        target = round(entry + target_points, 2)
    else:
        entry = option_ltp
        stoploss = round(entry + sl_points, 2)
        target = round(entry - target_points, 2)

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

    data = df if enriched else enrich_candles(df)
    row = data.iloc[-1]
    prev = data.iloc[-2]
    ts = row.get("timestamp")

    if not skip_session and not in_battle_session(ts):
        return None
    if _expiry_blocks_entry(ts, instrument_key):
        return None

    ema9 = float(row["ema9"])
    ema21 = float(row["ema21"])
    rsi_val = float(row["rsi14"])
    spot = float(row["close"])
    vwap = float(row.get("vwap", spot))

    call_ok = (
        _recent_cross(data, "CALL")
        and ema9 > ema21
        and 50 <= rsi_val <= 65
        and spot > vwap
        and _two_bar_momentum(data, "CALL")
    )
    put_ok = (
        _recent_cross(data, "PUT")
        and ema9 < ema21
        and 35 <= rsi_val <= 50
        and spot < vwap
        and _two_bar_momentum(data, "PUT")
    )

    if not call_ok and not put_ok:
        return None

    signal_type = "CALL" if call_ok else "PUT"
    risk = battle_risk(instrument_key)
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
    """Opening-range breakout — Bank Nifty P&L-focused setup."""
    if len(df) < 30:
        return None

    data = df if enriched else enrich_candles(df)
    row = data.iloc[-1]
    ts = row.get("timestamp")

    if not skip_session and not in_battle_session(ts):
        return None
    if _expiry_blocks_entry(ts, instrument_key):
        return None

    ist = _to_ist(ts)
    if ist is None:
        return None
    minutes = ist.hour * 60 + ist.minute
    # ORB entries mainly in morning window
    if minutes > 10 * 60 + 30:
        return None

    risk = battle_risk(instrument_key)
    orb = _session_orb(data, int(risk.get("orb_minutes", 15)))
    if not orb:
        return None

    spot = float(row["close"])
    prev_spot = float(data.iloc[-2]["close"])
    ema9 = float(row["ema9"])
    ema21 = float(row["ema21"])
    rsi_val = float(row["rsi14"])
    vol_ratio = float(row.get("volume_ratio") or 0)
    buffer = spot * 0.0003

    inside_or = orb["low"] <= prev_spot <= orb["high"]
    call_ok = (
        inside_or
        and spot > orb["high"] + buffer
        and ema9 > ema21
        and 52 <= rsi_val <= 66
        and vol_ratio >= 1.35
        and float(row["close"]) > float(row["open"])
        and _two_bar_momentum(data, "CALL")
    )
    put_ok = (
        inside_or
        and spot < orb["low"] - buffer
        and ema9 < ema21
        and 34 <= rsi_val <= 48
        and vol_ratio >= 1.35
        and float(row["close"]) < float(row["open"])
        and _two_bar_momentum(data, "PUT")
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
        "description": "Bank Nifty opening-range breakout — higher P&L, slightly wider DD",
        "evaluate": evaluate_orb_breakout,
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"],
        "instruments": ["banknifty"],
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
    else:
        order = ["ema_crossover_rsi"]

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
