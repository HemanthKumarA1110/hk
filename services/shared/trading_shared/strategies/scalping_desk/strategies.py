"""Scalping strategy variants — each tuned for different market conditions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd

from trading_shared.strategies.scalping_desk.engine import (
    ScalpSignal,
    compute_scalp_risk,
    enrich_candles,
    max_hold_bars,
    pick_strike,
    premium_risk_from_index,
    risk_profile,
)
from trading_shared.strategies.scalping_desk.market_context import in_trading_session

StrategyFn = Callable[..., ScalpSignal | None]


def _ema_bullish(df: pd.DataFrame) -> bool:
    if len(df) < 4:
        return False
    tail = df.tail(4)
    crossover = any(
        tail["ema9"].iloc[i] > tail["ema21"].iloc[i]
        and tail["ema9"].iloc[i - 1] <= tail["ema21"].iloc[i - 1]
        for i in range(1, len(tail))
    )
    return crossover or float(tail["ema9"].iloc[-1]) > float(tail["ema21"].iloc[-1])


def _ema_bearish(df: pd.DataFrame) -> bool:
    if len(df) < 2:
        return False
    tail = df.tail(4)
    crossover = any(
        tail["ema9"].iloc[i] < tail["ema21"].iloc[i]
        and tail["ema9"].iloc[i - 1] >= tail["ema21"].iloc[i - 1]
        for i in range(1, len(tail))
    )
    return crossover or float(tail["ema9"].iloc[-1]) < float(tail["ema21"].iloc[-1])


def _ema_separated(data: pd.DataFrame, spot: float, min_pct: float = 0.04) -> bool:
    row = data.iloc[-1]
    gap = abs(float(row["ema9"]) - float(row["ema21"]))
    return gap / max(spot, 1) * 100 >= min_pct


def _two_bar_momentum(data: pd.DataFrame, direction: str) -> bool:
    if len(data) < 3:
        return False
    c1, c2, c3 = data.iloc[-3], data.iloc[-2], data.iloc[-1]
    if direction == "CALL":
        return float(c2["close"]) > float(c2["open"]) and float(c3["close"]) > float(c3["open"])
    return float(c2["close"]) < float(c2["open"]) and float(c3["close"]) < float(c3["open"])


def _build_signal(
    *,
    strategy_id: str,
    strategy_label: str,
    signal_type: str,
    data: pd.DataFrame,
    timeframe: str,
    option_chain: dict[str, Any],
    instrument_key: str,
    conditions: list[str],
    target_mult: float = 1.0,
    stop_mult: float = 1.0,
    hold_bars: int | None = None,
) -> ScalpSignal | None:
    row = data.iloc[-1]
    spot = float(row["close"])
    atr = float(row["atr"] or spot * 0.002)
    strike_info = pick_strike(option_chain, spot, signal_type)
    if not strike_info:
        return None

    profile = risk_profile(instrument_key)
    stop_pts, target_pts = compute_scalp_risk(spot, atr, instrument_key)
    stop_pts = round(stop_pts * stop_mult, 2)
    target_pts = round(max(target_pts * target_mult, float(profile["min_target_pts"]) * 0.8), 2)
    max_hold = hold_bars or max_hold_bars(instrument_key)

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

    indicators = {
        "ema9": round(float(row["ema9"]), 2),
        "ema21": round(float(row["ema21"]), 2),
        "rsi": round(float(row["rsi14"]), 2),
        "vwap": round(float(row["vwap"]), 2),
        "supertrend": round(float(row["supertrend_dir"] or 0), 2),
        "volume_ratio": round(float(row["volume_ratio"]), 2),
        "atr": round(atr, 2),
        "spot": round(spot, 2),
        "index_stop_pts": stop_pts,
        "index_target_pts": target_pts,
        "max_hold_bars": max_hold,
        "strategy_id": strategy_id,
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
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


def evaluate_momentum_burst(
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
    """High-confluence momentum scalp — stricter filters for higher win rate."""
    if len(df) < 21:
        return None

    data = df if enriched else enrich_candles(df)
    row = data.iloc[-1]
    ts = row.get("timestamp")
    if not skip_session:
        from trading_shared.strategies.scalping_desk.battle_tested_scalp import in_battle_session

        if not in_battle_session(ts):
            return None

    params = params or {}
    vol_min = float(params.get("volume_spike_ratio", 1.35))
    if bool(row.get("volume_proxy")) or instrument_key in ("nifty50", "banknifty"):
        vol_min = float(params.get("index_volume_spike_ratio", 1.12))
    spot = float(row["close"])
    rsi_val = float(row["rsi14"])
    st_dir = float(row["supertrend_dir"] or 0)
    vol_ratio = float(row["volume_ratio"])
    vwap = float(row["vwap"])
    vol_ok = vol_ratio >= vol_min or bool(row.get("vol_spike"))

    if not _ema_separated(data, spot):
        return None

    call_ok = (
        spot > vwap
        and abs(spot - vwap) / spot * 100 <= 0.35
        and _ema_bullish(data)
        and 46 <= rsi_val <= 62
        and st_dir > 0
        and vol_ok
        and _two_bar_momentum(data, "CALL")
    )
    put_ok = (
        spot < vwap
        and abs(spot - vwap) / spot * 100 <= 0.35
        and _ema_bearish(data)
        and 40 <= rsi_val <= 52
        and st_dir < 0
        and vol_ok
        and _two_bar_momentum(data, "PUT")
    )
    if not call_ok and not put_ok:
        return None

    signal_type = "CALL" if call_ok else "PUT"
    return _build_signal(
        strategy_id="momentum_burst",
        strategy_label="Momentum Burst",
        signal_type=signal_type,
        data=data,
        timeframe=timeframe,
        option_chain=option_chain,
        instrument_key=instrument_key,
        conditions=[
            "ema_separated",
            "two_bar_momentum",
            "vwap_side",
            "volume_spike",
            "supertrend_aligned",
        ],
    )


def evaluate_vwap_bounce(
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
    """Mean-reversion bounce off VWAP in ranging markets."""
    if len(df) < 21:
        return None
    if not skip_session and not in_trading_session():
        return None

    data = df if enriched else enrich_candles(df)
    row = data.iloc[-1]
    prev = data.iloc[-2]
    spot = float(row["close"])
    atr = float(row["atr"] or spot * 0.002)
    vwap = float(row["vwap"])
    rsi_val = float(row["rsi14"])
    prev_rsi = float(prev["rsi14"])
    near_vwap = abs(spot - vwap) <= atr * 0.25

    call_ok = near_vwap and spot >= vwap and prev_rsi < 45 <= rsi_val <= 58 and float(row["close"]) > float(row["open"])
    put_ok = near_vwap and spot <= vwap and prev_rsi > 55 >= rsi_val >= 42 and float(row["close"]) < float(row["open"])
    if not call_ok and not put_ok:
        return None

    signal_type = "CALL" if call_ok else "PUT"
    return _build_signal(
        strategy_id="vwap_bounce",
        strategy_label="VWAP Bounce",
        signal_type=signal_type,
        data=data,
        timeframe=timeframe,
        option_chain=option_chain,
        instrument_key=instrument_key,
        conditions=["near_vwap", "rsi_reversal", "ranging_bounce"],
        target_mult=0.45,
        stop_mult=0.95,
        hold_bars=max(6, max_hold_bars(instrument_key) - 2),
    )


def evaluate_trend_follow(
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
    """Pullback entry in a strong trend — ride EMA9."""
    if len(df) < 25:
        return None
    if not skip_session and not in_trading_session():
        return None

    data = df if enriched else enrich_candles(df)
    row = data.iloc[-1]
    spot = float(row["close"])
    ema9 = float(row["ema9"])
    ema21 = float(row["ema21"])
    st_dir = float(row["supertrend_dir"] or 0)
    vol_ratio = float(row["volume_ratio"])
    pullback_pct = abs(spot - ema9) / spot * 100

    pullback_max = 0.14 if instrument_key == "banknifty" else 0.10
    vol_floor = 1.25 if instrument_key == "banknifty" else 1.35

    call_ok = (
        ema9 > ema21
        and st_dir > 0
        and spot > float(row["vwap"])
        and pullback_pct <= pullback_max
        and vol_ratio >= vol_floor
        and _ema_separated(data, spot)
        and float(row["close"]) > float(row["open"])
        and _two_bar_momentum(data, "CALL")
    )
    put_ok = (
        ema9 < ema21
        and st_dir < 0
        and spot < float(row["vwap"])
        and pullback_pct <= pullback_max
        and vol_ratio >= vol_floor
        and _ema_separated(data, spot)
        and float(row["close"]) < float(row["open"])
        and _two_bar_momentum(data, "PUT")
    )
    if not call_ok and not put_ok:
        return None

    signal_type = "CALL" if call_ok else "PUT"
    return _build_signal(
        strategy_id="trend_follow",
        strategy_label="Trend Follow",
        signal_type=signal_type,
        data=data,
        timeframe=timeframe,
        option_chain=option_chain,
        instrument_key=instrument_key,
        conditions=["ema_pullback", "trend_stack", "volume_confirm"],
        target_mult=0.65,
        stop_mult=1.1,
    )


def evaluate_volume_breakout(
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
    """Breakout on volume spike in high-volatility sessions."""
    if len(df) < 25:
        return None
    if not skip_session and not in_trading_session():
        return None

    data = df if enriched else enrich_candles(df)
    row = data.iloc[-1]
    window = data.iloc[-6:-1]
    spot = float(row["close"])
    st_dir = float(row["supertrend_dir"] or 0)
    vol_ratio = float(row["volume_ratio"])
    high5 = float(window["high"].max())
    low5 = float(window["low"].min())

    call_ok = (
        spot > high5
        and st_dir > 0
        and vol_ratio >= 1.7
        and _two_bar_momentum(data, "CALL")
        and _ema_separated(data, spot)
        and float(row["close"]) > float(row["open"])
    )
    put_ok = (
        spot < low5
        and st_dir < 0
        and vol_ratio >= 1.7
        and _two_bar_momentum(data, "PUT")
        and _ema_separated(data, spot)
        and float(row["close"]) < float(row["open"])
    )
    if not call_ok and not put_ok:
        return None

    signal_type = "CALL" if call_ok else "PUT"
    return _build_signal(
        strategy_id="volume_breakout",
        strategy_label="Volume Breakout",
        signal_type=signal_type,
        data=data,
        timeframe=timeframe,
        option_chain=option_chain,
        instrument_key=instrument_key,
        conditions=["range_break", "volume_surge", "supertrend_aligned"],
        target_mult=0.6,
        stop_mult=1.15,
    )


STRATEGY_REGISTRY: dict[str, dict[str, Any]] = {
    "momentum_burst": {
        "id": "momentum_burst",
        "label": "Momentum Burst",
        "description": "High-confluence momentum entries with 2-bar confirmation",
        "evaluate": evaluate_momentum_burst,
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"],
    },
    "vwap_bounce": {
        "id": "vwap_bounce",
        "label": "VWAP Bounce",
        "description": "Mean-reversion bounce at VWAP in sideways markets",
        "evaluate": evaluate_vwap_bounce,
        "best_regimes": ["RANGING", "LOW_VOLATILITY"],
    },
    "trend_follow": {
        "id": "trend_follow",
        "label": "Trend Follow",
        "description": "Pullback to EMA9 in established trends",
        "evaluate": evaluate_trend_follow,
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN"],
    },
    "volume_breakout": {
        "id": "volume_breakout",
        "label": "Volume Breakout",
        "description": "Range breakout on volume surge",
        "evaluate": evaluate_volume_breakout,
        "best_regimes": ["HIGH_VOLATILITY"],
    },
}


def list_strategies() -> list[dict[str, Any]]:
    return [
        {
            "id": meta["id"],
            "label": meta["label"],
            "description": meta["description"],
            "best_regimes": meta["best_regimes"],
        }
        for meta in STRATEGY_REGISTRY.values()
    ]


def evaluate_scalp(
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
    """Backward-compatible alias — uses momentum burst."""
    return evaluate_momentum_burst(
        df,
        timeframe,
        option_chain,
        lot_size,
        enriched=enriched,
        instrument_key=instrument_key,
        params=params,
        skip_session=skip_session,
    )
