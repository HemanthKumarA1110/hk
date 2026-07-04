from trading_shared.strategies.scalping_desk.market_regime_classifier import (
    apply_regime_to_position_size,
    classify_market_regime,
    classify_from_market_context,
    map_regime_to_legacy,
    regime_allows_signal,
)


def test_high_volatility_on_vix():
    out = classify_market_regime(vix=22, nifty_atr=11, banknifty_atr=38, ad_ratio=1.0)
    assert out["regime"] == "HIGH_VOLATILITY"
    assert out["adjustments"]["sl_multiplier"] == 1.3
    assert out["adjustments"]["size_multiplier"] == 0.7


def test_high_volatility_on_atr_spike():
    out = classify_market_regime(vix=14, nifty_atr=18, banknifty_atr=35, ad_ratio=1.0)
    assert out["regime"] == "HIGH_VOLATILITY"


def test_trending_bull():
    out = classify_market_regime(
        vix=14,
        nifty_atr=11,
        banknifty_atr=35,
        ad_ratio=1.35,
        fii_net=900,
        sgx_change=0.5,
        dow_change=0.35,
        direction="up",
        trend_strength=0.08,
        spot_change_pct=0.5,
    )
    assert out["regime"] == "TRENDING_BULL"
    assert out["adjustments"]["allowed_directions"] == "long_only"


def test_trending_bear():
    out = classify_market_regime(
        vix=14,
        nifty_atr=11,
        banknifty_atr=35,
        ad_ratio=0.7,
        fii_net=-800,
        sgx_change=-0.6,
        dow_change=-0.4,
        direction="down",
        trend_strength=0.09,
        spot_change_pct=-0.55,
    )
    assert out["regime"] == "TRENDING_BEAR"
    assert out["adjustments"]["allowed_directions"] == "short_only"


def test_event_driven_expiry():
    out = classify_market_regime(
        vix=21,
        nifty_atr=11,
        banknifty_atr=35,
        ad_ratio=1.0,
        is_expiry=True,
    )
    assert out["regime"] == "EVENT_DRIVEN"
    assert out["adjustments"]["allowed_directions"] == "none"


def test_range_bound():
    out = classify_market_regime(
        vix=13,
        nifty_atr=10,
        banknifty_atr=32,
        ad_ratio=1.02,
        spot_change_pct=0.1,
        trend_strength=0.02,
    )
    assert out["regime"] == "RANGE_BOUND"


def test_regime_blocks_put_in_bull():
    bull = classify_market_regime(
        vix=14,
        nifty_atr=11,
        banknifty_atr=35,
        ad_ratio=1.35,
        sgx_change=0.5,
        dow_change=0.35,
        direction="up",
        trend_strength=0.08,
        spot_change_pct=0.5,
        fii_net=900,
    )
    assert regime_allows_signal(bull, "CALL") is True
    assert regime_allows_signal(bull, "PUT") is False


def test_legacy_mapping():
    assert map_regime_to_legacy("TRENDING_BULL") == "trending_up"
    assert map_regime_to_legacy("RANGE_BOUND") == "ranging"


def test_size_multiplier_halves_lots():
    base = {
        "action": "TRADE",
        "lots": 2,
        "capital_at_risk": 2000,
        "risk_per_lot_inr": 1000,
        "reason": "2 lots",
    }
    regime = {"adjustments": {"size_multiplier": 0.7}}
    out = apply_regime_to_position_size(base, regime)
    assert out["lots"] == 1


def test_classify_from_market_context():
    out = classify_from_market_context(
        instrument_key="nifty50",
        market_ctx={"atr": 11.5, "direction": "up", "spot_change_pct": 0.4, "trend_strength": 0.07},
        macro_inputs={"vix": 14, "ad_ratio": 1.3, "sgx_change": 0.4, "fii_net": 600},
    )
    assert "regime" in out
    assert "confidence" in out
