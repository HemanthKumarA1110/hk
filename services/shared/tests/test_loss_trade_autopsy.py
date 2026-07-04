import pandas as pd

from trading_shared.strategies.scalping_desk.loss_trade_autopsy import (
    autopsy_losing_trade,
    save_loss_autopsy,
)


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, _ttl, value):
        self.store[key] = value


def _loss_trade(score=2, verdict="SKIP", regime="TRENDING_BULL", stop=7, atr=12, pnl=-7):
    return {
        "timestamp": "2026-06-02T10:00:00+05:30",
        "signal_type": "CALL",
        "strategy_id": "ema_crossover_rsi",
        "entry_spot": 23500.0,
        "exit": 23493.0,
        "pnl": pnl,
        "stop_pts": stop,
        "target_pts": 14.0,
        "bars_held": 3,
        "entry_index": 0,
        "exit_reason": "stop_loss",
        "indicators": {"spot": 23500.0, "atr": atr, "index_stop_pts": stop},
        "entry_validation": {"score": score, "verdict": verdict},
        "ai": {"regime": regime},
    }


def _df_after_recovery():
    return pd.DataFrame(
        {
            "close": [23500.0, 23493.0, 23495.0, 23510.0, 23520.0],
        }
    )


def test_bad_signal_autopsy():
    out = autopsy_losing_trade(instrument_key="nifty50", trade=_loss_trade(score=2))
    assert out["root_cause"] == "A"
    assert out["should_have_skipped"] is True
    assert out["update_blacklist"] is True


def test_bad_risk_tight_stop():
    out = autopsy_losing_trade(
        instrument_key="nifty50",
        trade=_loss_trade(score=5, verdict="TAKE", stop=5, atr=12),
    )
    assert out["root_cause"] == "C"
    assert "ATR" in out["description"] or "tight" in out["description"].lower()


def test_bad_timing_recovery():
    df = _df_after_recovery()
    out = autopsy_losing_trade(
        instrument_key="nifty50",
        trade=_loss_trade(score=5, verdict="TAKE"),
        df=df,
    )
    assert out["root_cause"] == "B"
    assert out["recovered_after_sl"] is True


def test_regime_mismatch():
    out = autopsy_losing_trade(
        instrument_key="nifty50",
        trade=_loss_trade(score=5, verdict="TAKE", regime="TRENDING_BEAR"),
        market_regime={"regime": "TRENDING_BEAR", "adjustments": {"allowed_directions": "short_only"}},
    )
    assert out["root_cause"] == "E"
    assert out["should_have_skipped"] is True


def test_correct_process():
    df = pd.DataFrame({"close": [23500.0, 23495.0, 23493.0]})
    out = autopsy_losing_trade(
        instrument_key="nifty50",
        trade=_loss_trade(score=5, verdict="TAKE", stop=10, atr=8),
        df=df,
        market_regime={"regime": "TRENDING_BULL", "adjustments": {"allowed_directions": "both"}},
    )
    assert out["root_cause"] == "D"
    assert out["should_have_skipped"] is False


def test_save_autopsy_blacklist():
    redis = _FakeRedis()
    autopsy = autopsy_losing_trade(instrument_key="nifty50", trade=_loss_trade(score=1))
    save_loss_autopsy(redis, 1, "nifty50", autopsy)
    assert redis.get("scalping:desk:1:nifty50:loss_autopsies")
    assert redis.get("scalping:desk:1:nifty50:setup_blacklist")


def test_skip_winning_trade():
    out = autopsy_losing_trade(
        instrument_key="nifty50",
        trade={**_loss_trade(), "pnl": 50},
    )
    assert out.get("skipped") is True
