"""Scalping strategy variants — each tuned for different market conditions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import pandas as pd

from trading_shared.strategies.scalping_desk.engine import (
    ScalpSignal,
    compute_scalp_risk,
    enrich_candles,
    long_premium_brackets,
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
    entry = option_ltp
    stoploss, target = long_premium_brackets(entry, sl_points, target_points)

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
    """High-confluence momentum scalp — Bank Nifty uses tunable mb_* defaults."""
    if len(df) < 21:
        return None

    data = df if enriched else enrich_candles(df)
    row = data.iloc[-1]
    ts = row.get("timestamp")
    if not skip_session:
        from trading_shared.strategies.scalping_desk.battle_tested_scalp import in_battle_session

        if not in_battle_session(ts, df=data, instrument_key=instrument_key):
            return None

    params = params or {}
    p: dict[str, Any] = {}
    if instrument_key == "banknifty":
        from trading_shared.strategies.scalping_desk.momentum_burst_tuning import merge_momentum_burst_params

        p = merge_momentum_burst_params(params)

    if instrument_key == "banknifty":
        vol_min = float(p.get("mb_index_volume_spike_ratio") or 1.12)
        if not (bool(row.get("volume_proxy")) or instrument_key in ("nifty50", "banknifty")):
            vol_min = float(p.get("mb_volume_spike_ratio") or 1.35)
        sep_pct = float(p.get("mb_ema_sep_pct") or 0.0)
        vwap_dist = float(p.get("mb_vwap_distance_pct") or 0.0)
        require_vwap = bool(p.get("mb_require_vwap", True))
        require_st = bool(p.get("mb_require_supertrend", False))
        require_mom = bool(p.get("mb_require_two_bar_momentum", False))
        call_lo = int(p.get("mb_rsi_call_min") or 46)
        call_hi = int(p.get("mb_rsi_call_max") or 62)
        put_lo = int(p.get("mb_rsi_put_min") or 40)
        put_hi = int(p.get("mb_rsi_put_max") or 52)
        hold_bars = int(p.get("mb_max_hold_bars") or 5)
        ema_mode = str(p.get("mb_ema_mode") or "or")
    else:
        vol_min = float(params.get("volume_spike_ratio", 1.35))
        if bool(row.get("volume_proxy")) or instrument_key in ("nifty50", "banknifty"):
            vol_min = float(params.get("index_volume_spike_ratio", 1.12))
        sep_pct = 0.04
        vwap_dist = 0.35
        require_vwap = True
        require_st = True
        require_mom = True
        call_lo, call_hi = 46, 62
        put_lo, put_hi = 40, 52
        hold_bars = None
        ema_mode = "or"

    spot = float(row["close"])
    rsi_val = float(row["rsi14"])
    st_dir = float(row["supertrend_dir"] or 0)
    vol_ratio = float(row["volume_ratio"])
    vwap = float(row["vwap"])
    vol_ok = vol_ratio >= vol_min or bool(row.get("vol_spike"))

    if sep_pct > 0 and not _ema_separated(data, spot, min_pct=sep_pct):
        return None

    dist = abs(spot - vwap) / max(spot, 1) * 100
    dist_ok = True if vwap_dist <= 0 else dist <= vwap_dist

    def _ema_ok(direction: str) -> bool:
        if ema_mode == "direction":
            if direction == "CALL":
                return float(row["ema9"]) > float(row["ema21"])
            return float(row["ema9"]) < float(row["ema21"])
        if ema_mode == "cross":
            if len(data) < 4:
                return False
            tail = data.tail(4)
            if direction == "CALL":
                return any(
                    tail["ema9"].iloc[i] > tail["ema21"].iloc[i]
                    and tail["ema9"].iloc[i - 1] <= tail["ema21"].iloc[i - 1]
                    for i in range(1, len(tail))
                )
            return any(
                tail["ema9"].iloc[i] < tail["ema21"].iloc[i]
                and tail["ema9"].iloc[i - 1] >= tail["ema21"].iloc[i - 1]
                for i in range(1, len(tail))
            )
        return _ema_bullish(data) if direction == "CALL" else _ema_bearish(data)

    call_ok = (
        _ema_ok("CALL")
        and call_lo <= rsi_val <= call_hi
        and (not require_vwap or spot > vwap)
        and dist_ok
        and (not require_st or st_dir > 0)
        and vol_ok
        and (not require_mom or _two_bar_momentum(data, "CALL"))
    )
    put_ok = (
        _ema_ok("PUT")
        and put_lo <= rsi_val <= put_hi
        and (not require_vwap or spot < vwap)
        and dist_ok
        and (not require_st or st_dir < 0)
        and vol_ok
        and (not require_mom or _two_bar_momentum(data, "PUT"))
    )
    if not call_ok and not put_ok:
        return None

    signal_type = "CALL" if call_ok else "PUT"
    conditions = ["vwap_side", "volume_spike"]
    if sep_pct > 0:
        conditions.insert(0, "ema_separated")
    if require_mom:
        conditions.append("two_bar_momentum")
    if require_st:
        conditions.append("supertrend_aligned")

    # Bank Nifty: scale ATR risk from shared profile to strategy-specific multipliers.
    stop_mult = 1.0
    target_mult = 1.0
    if instrument_key == "banknifty" and p:
        from trading_shared.strategies.scalping_desk.constants import RISK_PROFILES

        profile = RISK_PROFILES.get("banknifty", {})
        base_stop = float(profile.get("stop_atr_mult") or 1.2)
        base_tgt = float(profile.get("target_atr_mult") or 0.5)
        want_stop = float(p.get("mb_stop_atr_mult") or base_stop)
        want_tgt = float(p.get("mb_target_atr_mult") or base_tgt)
        stop_mult = want_stop / max(base_stop, 1e-9)
        target_mult = want_tgt / max(base_tgt, 1e-9)

    return _build_signal(
        strategy_id="momentum_burst",
        strategy_label="Momentum Burst",
        signal_type=signal_type,
        data=data,
        timeframe=timeframe,
        option_chain=option_chain,
        instrument_key=instrument_key,
        conditions=conditions,
        stop_mult=stop_mult,
        target_mult=target_mult,
        hold_bars=hold_bars,
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
    """Mean-reversion bounce off VWAP in ranging markets.

    Nifty 50 (SCALP-AD-002) and Bank Nifty (SCALP-AD-006) share tunable ``vb_*`` params.
    """
    if len(df) < 21:
        return None
    if not skip_session and not in_trading_session():
        return None

    from trading_shared.strategies.scalping_desk.constants import RISK_PROFILES
    from trading_shared.strategies.scalping_desk.vwap_bounce_tuning import merge_vwap_bounce_params

    data = df if enriched else enrich_candles(df)
    row = data.iloc[-1]
    prev = data.iloc[-2]
    spot = float(row["close"])
    atr = float(row["atr"] or spot * 0.002)
    vwap = float(row["vwap"])
    rsi_val = float(row["rsi14"])
    prev_rsi = float(prev["rsi14"])
    prev_spot = float(prev["close"])

    p = merge_vwap_bounce_params(params, instrument_key)
    near_atr = float(p.get("vb_near_atr_mult") or 0)
    near_pct = float(p.get("vb_near_pct") or 0)
    dist = abs(spot - vwap)
    near_ok = False
    if near_atr > 0:
        near_ok = near_ok or dist <= atr * near_atr
    if near_pct > 0:
        near_ok = near_ok or (dist / max(spot, 1) * 100 <= near_pct)
    if near_atr <= 0 and near_pct <= 0:
        near_ok = dist <= atr * 0.25

    side_mode = str(p.get("vb_side_mode") or "touch")
    disp = float(p.get("vb_side_displace_atr") or 0) * atr
    if side_mode == "displace":
        call_side = spot >= vwap + disp
        put_side = spot <= vwap - disp
    elif side_mode == "cross":
        # Bank AD-006 legacy: "cross" disables the side gate.
        # Nifty AD-002: require a VWAP cross into the bounce side.
        if instrument_key == "banknifty":
            call_side = put_side = True
        else:
            call_side = prev_spot < vwap and spot >= vwap
            put_side = prev_spot > vwap and spot <= vwap
    elif side_mode == "prev":
        call_side = spot >= vwap and prev_spot >= vwap
        put_side = spot <= vwap and prev_spot <= vwap
    else:
        call_side = spot >= vwap
        put_side = spot <= vwap

    turn = float(p.get("vb_rsi_turn_min") or 0)
    candle_mode = str(p.get("vb_candle_mode") or "off")
    multi = int(p.get("vb_multi_bar") or 1)
    close_loc = float(p.get("vb_close_loc_pct") or 0)

    def _candle_ok(r, direction: str) -> bool:
        o, c, h, l = float(r["open"]), float(r["close"]), float(r["high"]), float(r["low"])
        body = abs(c - o)
        rng = max(h - l, 1e-9)
        body_pct = body / rng
        if candle_mode == "off":
            color_ok = True
        elif candle_mode == "color":
            color_ok = (c > o) if direction == "CALL" else (c < o)
        else:
            need = {"body30": 0.30, "body40": 0.40, "body50": 0.50, "body60": 0.60}.get(candle_mode, 0.0)
            if direction == "CALL":
                color_ok = c > o and body_pct >= need
            else:
                color_ok = c < o and body_pct >= need
        if not color_ok:
            return False
        if close_loc <= 0:
            return True
        if direction == "CALL":
            return (c - l) / rng >= close_loc
        return (h - c) / rng >= close_loc

    def _multi_ok(direction: str) -> bool:
        if multi <= 1:
            return _candle_ok(row, direction)
        if len(data) < multi:
            return False
        return all(_candle_ok(data.iloc[-i], direction) for i in range(1, multi + 1))

    call_ok = (
        near_ok
        and call_side
        and prev_rsi < float(p["vb_call_prev_rsi_max"])
        and float(p["vb_call_rsi_min"]) <= rsi_val <= float(p["vb_call_rsi_max"])
        and (rsi_val - prev_rsi) >= turn
        and _multi_ok("CALL")
    )
    put_ok = (
        near_ok
        and put_side
        and prev_rsi > float(p["vb_put_prev_rsi_min"])
        and float(p["vb_put_rsi_min"]) <= rsi_val <= float(p["vb_put_rsi_max"])
        and (prev_rsi - rsi_val) >= turn
        and _multi_ok("PUT")
    )
    if not call_ok and not put_ok:
        return None

    profile = RISK_PROFILES.get(instrument_key, RISK_PROFILES["nifty50"])
    base_stop = float(profile.get("stop_atr_mult") or 1.2)
    base_tgt = float(profile.get("target_atr_mult") or 0.55)
    want_stop = float(p.get("vb_stop_atr_mult") or base_stop)
    want_tgt = float(p.get("vb_target_atr_mult") or base_tgt)
    hold_bars = int(p.get("vb_max_hold_bars") or max(6, max_hold_bars(instrument_key) - 2))
    return _build_signal(
        strategy_id="vwap_bounce",
        strategy_label="VWAP Bounce",
        signal_type="CALL" if call_ok else "PUT",
        data=data,
        timeframe=timeframe,
        option_chain=option_chain,
        instrument_key=instrument_key,
        conditions=["near_vwap", "rsi_reversal", "ranging_bounce"],
        stop_mult=want_stop / max(base_stop, 1e-9),
        target_mult=want_tgt / max(base_tgt, 1e-9),
        hold_bars=hold_bars,
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
