from zoneinfo import ZoneInfo

from trading_shared.strategies.scalping_desk.eod_self_review import (
    filter_trades_for_day,
    run_eod_self_review,
)

IST = ZoneInfo("Asia/Kolkata")


def _trade(ts, score, verdict, pnl, stop=7, atr=8):
    return {
        "timestamp": ts,
        "signal_type": "CALL",
        "strategy_id": "ema_crossover_rsi",
        "pnl": pnl,
        "stop_pts": stop,
        "exit_reason": "stop_loss" if pnl < 0 else "target",
        "indicators": {"atr": atr, "index_stop_pts": stop},
        "entry_validation": {"score": score, "verdict": verdict},
    }


def test_good_trade_classification():
    trades = [
        _trade("2026-06-02T10:00:00+05:30", 5, "TAKE", 120),
    ]
    out = run_eod_self_review(
        instrument_key="nifty50",
        trades=trades,
        regime="TRENDING_BULL",
        day="2026-06-02",
    )
    assert len(out["good_trades"]) == 1
    assert out["avoidable_trades"] == []


def test_avoidable_weak_score():
    trades = [
        _trade("2026-06-02T10:00:00+05:30", 2, "SKIP", -50),
    ]
    out = run_eod_self_review(
        instrument_key="nifty50",
        trades=trades,
        day="2026-06-02",
    )
    assert len(out["avoidable_trades"]) == 1
    assert out["avoidable_trades"][0]["validation_score"] == 2


def test_sl_too_tight():
    trades = [
        _trade("2026-06-02T10:00:00+05:30", 5, "TAKE", -7, stop=5, atr=10),
        _trade("2026-06-02T10:15:00+05:30", 4, "TAKE", -7, stop=5, atr=10),
    ]
    out = run_eod_self_review(instrument_key="nifty50", trades=trades, day="2026-06-02")
    assert out["sl_assessment"] == "too_tight"
    assert out["parameter_suggestions"]["sl_multiplier_adjustment"] == 0.15


def test_filter_trades_for_day():
    trades = [
        _trade("2026-06-02T10:00:00+05:30", 5, "TAKE", 10),
        _trade("2026-06-01T10:00:00+05:30", 5, "TAKE", 10),
    ]
    assert len(filter_trades_for_day(trades, "2026-06-02")) == 1


def test_empty_day_review():
    out = run_eod_self_review(instrument_key="nifty50", trades=[], day="2026-06-02")
    assert out["trade_count"] == 0
    assert out["timing_compliance_pct"] == 100.0
    assert "top_lesson" in out
