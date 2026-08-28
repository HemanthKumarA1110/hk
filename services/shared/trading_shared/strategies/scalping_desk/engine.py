"""Multi-confirmation option scalping strategy for NIFTY / BANKNIFTY desk."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from trading_shared.market.scrip_master import normalize_scrip_strike, parse_option_strike_symbol
from trading_shared.strategies.scalping_desk.constants import (
    OPTION_DELTA_EST,
    PREMIUM_SL_PCT,
    PREMIUM_TGT_PCT,
    RISK_PROFILES,
    option_contract_suffix,
    validate_option_buy_contract,
)
from trading_shared.strategies.ta import ema, rsi, supertrend, vwap


@dataclass
class ScalpSignal:
    signal_type: str  # CALL | PUT
    strike: float
    option_symbol: str
    option_token: str
    entry: float
    target: float
    stoploss: float
    timeframe: str
    indicators: dict[str, Any]
    conditions_met: list[str]
    timestamp: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_type": self.signal_type,
            "strike": self.strike,
            "option_symbol": self.option_symbol,
            "option_token": self.option_token,
            "entry": self.entry,
            "target": self.target,
            "stoploss": self.stoploss,
            "timeframe": self.timeframe,
            "indicators": self.indicators,
            "conditions_met": self.conditions_met,
            "timestamp": self.timestamp,
            "status": "pending",
            "strategy_id": self.indicators.get("strategy_id"),
        }


def risk_profile(instrument_key: str) -> dict[str, float | int]:
    return RISK_PROFILES.get(instrument_key, RISK_PROFILES["nifty50"])


def compute_scalp_risk(
    spot: float,
    atr: float,
    instrument_key: str = "nifty50",
) -> tuple[float, float]:
    """Index-point stop/target for AI quick-scalp v3."""
    profile = risk_profile(instrument_key)
    min_target = float(profile["min_target_pts"])
    stop_pts = max(atr * float(profile["stop_atr_mult"]), spot * 0.0002)
    target_pts = max(atr * float(profile["target_atr_mult"]), min_target)
    return round(stop_pts, 2), round(target_pts, 2)


def max_hold_bars(instrument_key: str) -> int:
    return int(risk_profile(instrument_key)["max_hold_bars"])


def premium_risk_from_index(
    option_ltp: float,
    stop_pts: float,
    target_pts: float,
) -> tuple[float, float]:
    """Map index-point risk to tight option premium stop/target."""
    sl = max(stop_pts * OPTION_DELTA_EST, option_ltp * PREMIUM_SL_PCT, 3.0)
    tgt = max(target_pts * OPTION_DELTA_EST, option_ltp * PREMIUM_TGT_PCT, 2.0)
    return round(sl, 2), round(tgt, 2)


def long_premium_brackets(entry: float, sl_points: float, target_points: float) -> tuple[float, float]:
    """Stop and target for a long CE/PE (premium up = profit)."""
    entry_px = float(entry)
    stop = round(max(0.05, entry_px - abs(float(sl_points))), 2)
    target = round(entry_px + abs(float(target_points)), 2)
    return stop, target


def normalize_long_premium_levels(entry: float, target: float, stoploss: float) -> tuple[float, float]:
    """Force long-option geometry even if a PUT signal stored inverted prices."""
    entry_px = float(entry or 0)
    if entry_px <= 0:
        return float(stoploss or 0), float(target or 0)
    tgt_dist = abs(float(target) - entry_px) if target else entry_px * PREMIUM_TGT_PCT
    sl_dist = abs(entry_px - float(stoploss)) if stoploss else entry_px * PREMIUM_SL_PCT
    return (
        round(max(0.05, entry_px - sl_dist), 2),
        round(entry_px + tgt_dist, 2),
    )


def enrich_candles(df: pd.DataFrame) -> pd.DataFrame:
    """Compute scalping indicators on OHLCV frame."""
    out = df.copy()
    for col in ("open", "high", "low", "close", "volume"):
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    out["ema9"] = ema(out["close"], 9)
    out["ema21"] = ema(out["close"], 21)
    out["rsi14"] = rsi(out["close"], 14)
    tp = (out["high"] + out["low"] + out["close"]) / 3
    # Angel One NSE index candles often report zero volume — use range + body as activity proxy.
    if float(out["volume"].sum()) <= 0:
        body = (out["close"] - out["open"]).abs()
        out["activity"] = (out["high"] - out["low"]).abs() + body * 0.5
        out["vol_avg20"] = out["activity"].rolling(20, min_periods=5).mean()
        out["vol_std20"] = out["activity"].rolling(20, min_periods=5).std().fillna(0)
        base = out["vol_avg20"].replace(0, 1)
        out["volume_ratio"] = out["activity"] / base
        out["vol_spike"] = (out["volume_ratio"] > 1.2) | (
            out["activity"] > out["vol_avg20"] + out["vol_std20"] * 0.5
        )
        out["volume_proxy"] = True
        out["vwap"] = tp.expanding().mean()
    else:
        out["volume_proxy"] = False
        out["vwap"] = vwap(out["high"], out["low"], out["close"], out["volume"])
        out["vol_avg20"] = out["volume"].rolling(20, min_periods=1).mean()
        out["volume_ratio"] = out["volume"] / out["vol_avg20"].replace(0, 1)
        out["vol_spike"] = out["volume_ratio"] > 1.5
    out["supertrend_dir"] = supertrend(out, period=10, multiplier=3.0)
    out["atr"] = (out["high"] - out["low"]).rolling(10, min_periods=1).mean()
    out["adx14"] = _adx(out["high"], out["low"], out["close"], period=14)
    return out


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder ADX(period) for trend-strength gating."""
    high = pd.to_numeric(high, errors="coerce").fillna(0.0)
    low = pd.to_numeric(low, errors="coerce").fillna(0.0)
    close = pd.to_numeric(close, errors="coerce").fillna(0.0)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    alpha = 1 / period
    atr_w = tr.ewm(alpha=alpha, adjust=False).mean().replace(0, pd.NA)
    plus_di = 100 * plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_w
    minus_di = 100 * minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_w
    di_sum = (plus_di + minus_di).replace(0, pd.NA)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    dx = pd.to_numeric(dx, errors="coerce").fillna(0.0)
    return dx.ewm(alpha=alpha, adjust=False).mean().fillna(0.0)


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
    """Evaluate momentum burst (backward-compatible entry point)."""
    from trading_shared.strategies.scalping_desk.strategies import evaluate_momentum_burst

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


def estimate_option_mark_premium(
    entry_premium: float,
    signal_type: str,
    entry_spot: float,
    spot: float,
) -> float:
    """Mark long CE/PE premium from index move (backtest / fallback LTP)."""
    move = spot - entry_spot
    if str(signal_type).upper() == "PUT":
        move = -move
    return max(0.05, float(entry_premium) + move * OPTION_DELTA_EST)


def pick_strike(chain: dict[str, Any], spot: float, signal_type: str) -> dict[str, Any] | None:
    """Pick ATM option to BUY (CE for CALL, PE for PUT)."""
    suffix = option_contract_suffix(signal_type)
    rows = chain.get("rows") or []
    if isinstance(rows, dict):
        rows = list(rows.values())

    candidates = []
    for row in rows:
        symbol = str(row.get("symbol") or "")
        if not symbol.endswith(suffix):
            continue
        strike = row.get("strike")
        if strike is None:
            strike = _parse_strike(symbol)
        strike = normalize_scrip_strike(float(strike or spot), spot)
        candidates.append({**row, "strike": strike, "symbol": symbol})

    if not candidates:
        step = 50 if spot > 10000 else 50
        atm = round(spot / step) * step
        return {
            "symbol": f"ATM{suffix}",
            "strike": atm,
            "ltp": max(spot * 0.005, 10),
            "token": "",
            "oi": 0,
        }

    candidates.sort(key=lambda r: abs(float(r["strike"]) - spot))
    best = candidates[0]
    if not validate_option_buy_contract(str(best.get("symbol") or ""), signal_type):
        return None
    return best


def classify_strikes(chain: dict[str, Any], spot: float) -> dict[str, Any]:
    """Return ATM / ITM / OTM CE and PE with live stats."""
    rows = chain.get("rows") or []
    if isinstance(rows, dict):
        rows = list(rows.values())

    ce = [r for r in rows if str(r.get("symbol", "")).endswith("CE")]
    pe = [r for r in rows if str(r.get("symbol", "")).endswith("PE")]
    def _row_strike(row: dict) -> float:
        raw = row.get("strike") or _parse_strike(str(row.get("symbol"))) or spot
        return normalize_scrip_strike(float(raw), spot)

    ce.sort(key=lambda r: abs(_row_strike(r) - spot))
    pe.sort(key=lambda r: abs(_row_strike(r) - spot))

    def pack(row: dict | None, label: str) -> dict | None:
        if not row:
            return None
        strike = normalize_scrip_strike(
            float(row.get("strike") or _parse_strike(str(row.get("symbol"))) or spot),
            spot,
        )
        prev = float(row.get("close") or row.get("ltp") or 0)
        ltp = float(row.get("ltp") or prev)
        chg = ((ltp - prev) / prev * 100) if prev else 0
        return {
            "label": label,
            "symbol": row.get("symbol"),
            "strike": strike,
            "ltp": ltp,
            "change_pct": round(chg, 2),
            "volume": row.get("volume", 0),
            "oi": row.get("oi", 0),
        }

    atm_ce = pack(ce[0] if ce else None, "ATM CE")
    atm_pe = pack(pe[0] if pe else None, "ATM PE")
    itm_ce = pack(ce[1] if len(ce) > 1 else None, "ITM CE")
    otm_ce = pack(ce[2] if len(ce) > 2 else None, "OTM CE")
    itm_pe = pack(pe[1] if len(pe) > 1 else None, "ITM PE")
    otm_pe = pack(pe[2] if len(pe) > 2 else None, "OTM PE")
    return {
        "spot": spot,
        "atm_ce": atm_ce,
        "atm_pe": atm_pe,
        "itm_ce": itm_ce,
        "otm_ce": otm_ce,
        "itm_pe": itm_pe,
        "otm_pe": otm_pe,
    }


def _parse_strike(symbol: str) -> float | None:
    return parse_option_strike_symbol(symbol)


def should_exit_index(
    signal_type: str,
    spot: float,
    entry_spot: float,
    target_pts: float,
    stop_pts: float,
    indicators: dict[str, Any] | None = None,
    *,
    bars_held: int = 0,
    max_hold: int | None = None,
    trail_floor_move: float | None = None,
) -> tuple[bool, str]:
    """Quick exit: target, tight stop, trail lock, or max-hold time stop."""
    move = spot - entry_spot
    if signal_type == "CALL":
        if move >= target_pts:
            return True, "target_hit"
        if trail_floor_move is not None and move > 0 and move <= trail_floor_move:
            return True, "trail_stop"
        if move <= -stop_pts:
            return True, "stoploss_hit"
    else:
        put_move = -move
        if put_move >= target_pts:
            return True, "target_hit"
        if trail_floor_move is not None and put_move > 0 and put_move <= trail_floor_move:
            return True, "trail_stop"
        if put_move >= stop_pts:
            return True, "stoploss_hit"
    if max_hold and bars_held >= max_hold:
        return True, "time_exit"
    return False, ""


def should_exit(
    signal_type: str,
    current_ltp: float,
    entry: float,
    target: float,
    stoploss: float,
    indicators: dict[str, Any],
    extended: bool = False,
    original_target: float | None = None,
) -> tuple[bool, str]:
    """Exit a long CE/PE when premium hits target (up) or stop (down)."""
    sl, tgt = normalize_long_premium_levels(entry, target, stoploss)
    if current_ltp >= tgt > 0:
        return True, "target_hit"
    if sl > 0 and current_ltp <= sl:
        return True, "stoploss_hit"
    if extended:
        orig = original_target or tgt
        if current_ltp >= orig * 2.5:
            return True, "extended_cap"
    return False, ""
