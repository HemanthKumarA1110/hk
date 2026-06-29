"""Strategy engine metadata exposed to the UI."""

from __future__ import annotations

from trading_shared.strategies.scoring import INTRADAY_MIN_SCORE, SCALPING_MIN_SCORE, SWING_MIN_SCORE

ConfirmationMeta = dict[str, str | float]

ENGINE_REGISTRY: dict[str, dict] = {
    "scalping": {
        "engine": "scalping",
        "strategy_name": "multi_confirmation_scalp",
        "title": "Scalping (NIFTY / BANKNIFTY)",
        "summary": "Index options scalping on 1m / 3m / 5m with ORB, VWAP, OI, and PCR filters.",
        "universe": "NIFTY & BANKNIFTY index options",
        "timeframes": ["1m", "3m", "5m"],
        "min_score": SCALPING_MIN_SCORE,
        "target_logic": "Fixed points target (NIFTY 25 pts, BANKNIFTY 40 pts) with 12 pt stop",
        "confirmations": [
            {"name": "orb_breakout", "weight": 12, "label": "Opening range breakout"},
            {"name": "vwap_bounce", "weight": 10, "label": "VWAP bounce / rejection"},
            {"name": "vwap_breakout", "weight": 8, "label": "VWAP distance breakout"},
            {"name": "ema_momentum", "weight": 10, "label": "EMA 9 vs 20 momentum"},
            {"name": "volume_spike", "weight": 12, "label": "Volume spike"},
            {"name": "oi_shift", "weight": 14, "label": "Open interest shift"},
            {"name": "pcr_bias", "weight": 8, "label": "PCR bias (0.7–1.3 band)"},
            {"name": "gamma_momentum", "weight": 10, "label": "Gamma / volume momentum"},
            {"name": "liquidity_ok", "weight": 8, "label": "Liquidity check"},
            {"name": "fake_breakout_filter", "weight": 8, "label": "Fake breakout filter"},
        ],
    },
    "intraday": {
        "engine": "intraday",
        "strategy_name": "intraday_multi",
        "title": "Intraday Top Picks",
        "summary": "Nifty stocks from scanner hits + top 20 Nifty 50, scored on momentum and trend.",
        "universe": "Market scanner hits + top 20 Nifty 50 equities",
        "timeframes": ["15m"],
        "min_score": INTRADAY_MIN_SCORE,
        "target_logic": "2R target from prior bar high/low stop",
        "confirmations": [
            {"name": "relative_volume", "weight": 12, "label": "Relative volume ≥ 2x"},
            {"name": "breakout", "weight": 10, "label": "Day high breakout"},
            {"name": "gap", "weight": 8, "label": "Gap up / gap down"},
            {"name": "sector_leader", "weight": 10, "label": "Sector leader strength"},
            {"name": "momentum", "weight": 10, "label": "Price momentum / RSI band"},
            {"name": "ema_trend", "weight": 10, "label": "EMA 20 vs 50 trend"},
            {"name": "vwap_trend", "weight": 8, "label": "Price vs VWAP"},
            {"name": "supertrend", "weight": 8, "label": "Supertrend alignment"},
            {"name": "rsi_pullback", "weight": 8, "label": "RSI pullback zone (45–65)"},
            {"name": "macd_momentum", "weight": 8, "label": "MACD vs signal line"},
            {"name": "bollinger_squeeze_breakout", "weight": 8, "label": "Bollinger band breakout"},
        ],
    },
    "swing": {
        "engine": "swing",
        "strategy_name": "swing_multi",
        "title": "Swing Setups",
        "summary": "Daily / weekly Nifty 50 swing setups with multi-timeframe trend alignment.",
        "universe": "Full Nifty 50 equities",
        "timeframes": ["1d", "1w"],
        "min_score": SWING_MIN_SCORE,
        "target_logic": "8–12% move target based on score; stop at prior bar extreme",
        "confirmations": [
            {"name": "breakout_retest", "weight": 10, "label": "Breakout retest pattern"},
            {"name": "volume_breakout", "weight": 10, "label": "Volume > 1.5× 20-day avg"},
            {"name": "mtf_alignment", "weight": 12, "label": "Weekly trend alignment"},
            {"name": "ma_crossover", "weight": 10, "label": "EMA 20 / 50 crossover"},
            {"name": "darvas_box", "weight": 8, "label": "Darvas box breakout"},
            {"name": "rsi_reversal", "weight": 8, "label": "RSI trend confirmation"},
            {"name": "support_accumulation", "weight": 8, "label": "Support accumulation"},
            {"name": "fib_pullback", "weight": 8, "label": "Fibonacci pullback zone"},
            {"name": "delivery_volume_proxy", "weight": 8, "label": "Rising delivery volume proxy"},
        ],
    },
}


def engine_configs() -> list[dict]:
    return list(ENGINE_REGISTRY.values())
