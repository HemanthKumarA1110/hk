from datetime import datetime
from zoneinfo import ZoneInfo

from trading_shared.strategies.scalping_desk.weekly_parameter_tuner import (
    aggregate_weekly_stats,
    config_patch_from_tuning,
    params_from_config,
    tune_weekly_parameters,
)

IST = ZoneInfo("Asia/Kolkata")
ANCHOR = datetime(2026, 6, 6, 15, 0, tzinfo=IST)


def _trade(day, pnl, regime="TRENDING_BULL"):
    return {
        "timestamp": f"{day}T10:00:00+05:30",
        "pnl": pnl,
        "signal_type": "CALL",
        "ai": {"regime": regime},
    }


def test_tighten_on_weak_week():
    trades = [_trade("2026-06-02", -50), _trade("2026-06-03", -40), _trade("2026-06-04", 30)]
    out = tune_weekly_parameters(
        config={"params": {"volume_spike_ratio": 1.3, "rsi_call_min": 50, "stop_atr_mult": 1.2}},
        trades=trades,
        days=5,
        anchor=ANCHOR,
    )
    assert out["mode"] == "tighten"
    assert out["vol_ratio"] > 1.3
    assert out["change_magnitude"] in ("minor", "moderate", "major")


def test_loosen_on_strong_week():
    trades = [_trade(f"2026-06-0{i}", 80) for i in range(2, 7)]
    out = tune_weekly_parameters(
        config={"params": {"volume_spike_ratio": 1.3, "rsi_call_min": 50}},
        trades=trades,
        days=5,
        anchor=ANCHOR,
    )
    assert out["mode"] == "loosen"
    assert out["vol_ratio"] < 1.3


def test_hold_in_middle_band():
    trades = [_trade("2026-06-02", 50), _trade("2026-06-02", 40), _trade("2026-06-02", -60)]
    out = tune_weekly_parameters(config={"params": {}}, trades=trades, days=5, anchor=ANCHOR)
    assert out["mode"] == "hold"


def test_aggregate_stats():
    trades = [_trade("2026-06-02", 100), _trade("2026-06-02", -50)]
    stats = aggregate_weekly_stats(trades=trades, days=5, anchor=ANCHOR)
    assert stats["trade_count"] >= 2
    assert "profit_factor" in stats


def test_config_patch():
    tuning = tune_weekly_parameters(
        config={"params": {"volume_spike_ratio": 1.3}},
        trades=[_trade("2026-06-02", -100)],
        days=5,
        anchor=ANCHOR,
    )
    patch = config_patch_from_tuning(tuning)
    assert patch["volume_spike_ratio"] == tuning["vol_ratio"]
    assert params_from_config({"params": patch})["vol_ratio"] == tuning["vol_ratio"]
