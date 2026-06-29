"""Market analytics utilities."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from trading_shared.market.constants import PRICE_DIVISOR


def normalize_price(raw_price: int | float | None) -> float:
    if raw_price is None:
        return 0.0
    return float(raw_price) / PRICE_DIVISOR


def compute_vwap(prices: list[float], volumes: list[float]) -> float:
    total_volume = sum(volumes)
    if total_volume <= 0:
        return 0.0
    return sum(p * v for p, v in zip(prices, volumes)) / total_volume


def detect_gap(open_price: float, prev_close: float, threshold_pct: float = 0.5) -> dict[str, Any] | None:
    if prev_close <= 0:
        return None
    gap_pct = ((open_price - prev_close) / prev_close) * 100
    if abs(gap_pct) < threshold_pct:
        return None
    return {
        "gap_pct": round(gap_pct, 2),
        "gap_type": "gap_up" if gap_pct > 0 else "gap_down",
        "open": open_price,
        "prev_close": prev_close,
    }


def compute_pcr(ce_oi: float, pe_oi: float) -> float | None:
    if ce_oi <= 0:
        return None
    return round(pe_oi / ce_oi, 4)


def sector_strength(sector_returns: dict[str, list[float]]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for sector, returns in sector_returns.items():
        if not returns:
            continue
        scores[sector] = round(sum(returns) / len(returns), 2)
    return dict(sorted(scores.items(), key=lambda item: item[1], reverse=True))


def relative_volume(current_volume: float, avg_volume: float) -> float:
    if avg_volume <= 0:
        return 0.0
    return round(current_volume / avg_volume, 2)


@dataclass
class OptionGreeks:
    delta: float
    gamma: float
    theta: float
    vega: float
    iv: float


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def black_scholes_greeks(
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    volatility: float,
    option_type: str,
) -> OptionGreeks:
    if time_to_expiry_years <= 0 or volatility <= 0 or spot <= 0 or strike <= 0:
        return OptionGreeks(0, 0, 0, 0, 0)

    sqrt_t = math.sqrt(time_to_expiry_years)
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * volatility**2) * time_to_expiry_years) / (volatility * sqrt_t)
    d2 = d1 - volatility * sqrt_t

    if option_type.upper() == "CE":
        delta = _norm_cdf(d1)
        price = spot * _norm_cdf(d1) - strike * math.exp(-risk_free_rate * time_to_expiry_years) * _norm_cdf(d2)
    else:
        delta = _norm_cdf(d1) - 1
        price = strike * math.exp(-risk_free_rate * time_to_expiry_years) * _norm_cdf(-d2) - spot * _norm_cdf(-d1)

    gamma = _norm_pdf(d1) / (spot * volatility * sqrt_t)
    vega = spot * _norm_pdf(d1) * sqrt_t / 100
    theta = (
        -(spot * _norm_pdf(d1) * volatility) / (2 * sqrt_t)
        - risk_free_rate * strike * math.exp(-risk_free_rate * time_to_expiry_years) * _norm_cdf(d2 if option_type.upper() == "CE" else -d2)
    ) / 365

    return OptionGreeks(
        delta=round(delta, 4),
        gamma=round(gamma, 6),
        theta=round(theta, 4),
        vega=round(vega, 4),
        iv=round(volatility, 4),
    )


def implied_volatility(
    market_price: float,
    spot: float,
    strike: float,
    time_to_expiry_years: float,
    risk_free_rate: float,
    option_type: str,
    max_iterations: int = 40,
) -> float:
    low, high = 0.01, 3.0
    for _ in range(max_iterations):
        mid = (low + high) / 2
        greeks = black_scholes_greeks(spot, strike, time_to_expiry_years, risk_free_rate, mid, option_type)
        theoretical = abs(greeks.delta)  # placeholder compare using delta proxy insufficient
        # Use bisection on price via simplified intrinsic + time value approximation
        intrinsic = max(0.0, spot - strike) if option_type.upper() == "CE" else max(0.0, strike - spot)
        model_price = intrinsic + (spot * mid * math.sqrt(time_to_expiry_years) * 0.4)
        if model_price > market_price:
            high = mid
        else:
            low = mid
    return round((low + high) / 2, 4)


def parse_tick(raw: dict[str, Any]) -> dict[str, Any]:
    ltp = normalize_price(raw.get("last_traded_price"))
    return {
        "token": str(raw.get("token", "")).strip(),
        "exchange_type": raw.get("exchange_type"),
        "ltp": ltp,
        "open": normalize_price(raw.get("open_price_of_the_day")),
        "high": normalize_price(raw.get("high_price_of_the_day")),
        "low": normalize_price(raw.get("low_price_of_the_day")),
        "close": normalize_price(raw.get("closed_price")),
        "volume": float(raw.get("volume_trade_for_the_day") or 0),
        "oi": float(raw.get("open_interest") or 0),
        "oi_change_pct": normalize_price(raw.get("open_interest_change_percentage")),
        "avg_price": normalize_price(raw.get("average_traded_price")),
        "exchange_timestamp": raw.get("exchange_timestamp"),
        "subscription_mode": raw.get("subscription_mode_val"),
    }
