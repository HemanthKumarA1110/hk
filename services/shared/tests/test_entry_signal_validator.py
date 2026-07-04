from trading_shared.strategies.scalping_desk.entry_signal_validator import (
    validate_entry_signal,
    validate_from_signal,
    verdict_allows_entry,
)


def test_take_on_full_checklist():
    out = validate_entry_signal(
        direction="LONG",
        price=100.0,
        indicator_name="ema crossover",
        ema9=101.0,
        ema21=99.0,
        rsi=62.0,
        vwap=99.5,
        vol_ratio=1.35,
        timestamp="2025-06-02T10:00:00+05:30",
    )
    assert out["score"] >= 4
    assert out["verdict"] == "TAKE"
    assert out["weak_factors"] == []
    assert out["sl"] < out["entry_price"] < out["target"]


def test_skip_on_neutral_rsi_and_low_volume():
    out = validate_entry_signal(
        direction="LONG",
        price=100.0,
        indicator_name="test",
        ema9=98.0,
        ema21=99.0,
        rsi=50.0,
        vwap=101.0,
        vol_ratio=1.0,
        timestamp="2025-06-02T11:00:00+05:30",
    )
    assert out["score"] < 3
    assert out["verdict"] == "SKIP"
    assert "rsi_zone" in out["weak_factors"]
    assert "volume" in out["weak_factors"]


def test_wait_on_three_factors():
    out = validate_entry_signal(
        direction="SHORT",
        price=100.0,
        indicator_name="test",
        ema9=101.0,
        ema21=99.0,
        rsi=50.0,
        vwap=101.0,
        vol_ratio=1.25,
        timestamp="2025-06-02T10:00:00+05:30",
    )
    assert out["score"] == 3
    assert out["verdict"] == "WAIT"


def test_validate_from_signal():
    signal = {
        "signal_type": "CALL",
        "timestamp": "2025-06-02T10:00:00+05:30",
        "strategy_id": "ema_crossover_rsi",
        "indicators": {
            "spot": 25000,
            "ema9": 25010,
            "ema21": 24990,
            "rsi": 56,
            "vwap": 24995,
            "volume_ratio": 1.3,
        },
    }
    out = validate_from_signal("nifty50", signal, targets={"stop_pts": 7, "target_pts": 14})
    assert out["verdict"] in ("TAKE", "WAIT", "SKIP")
    assert out["entry_price"] == 25000


def test_verdict_allows_entry():
    assert verdict_allows_entry({"verdict": "TAKE"}) is True
    assert verdict_allows_entry({"verdict": "WAIT"}) is False
