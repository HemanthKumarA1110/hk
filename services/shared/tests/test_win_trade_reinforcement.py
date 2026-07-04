import pandas as pd

from trading_shared.strategies.scalping_desk.win_trade_reinforcement import (
    reinforce_winning_trade,
    save_win_reinforcement,
)


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, _ttl, value):
        self.store[key] = value


def _win_trade(score=5, exit_reason="target_hit", pnl=14, target=14, stop=7):
    return {
        "timestamp": "2026-06-02T10:05:00+05:30",
        "signal_type": "CALL",
        "strategy_id": "ema_crossover_rsi",
        "entry_spot": 23500.0,
        "exit": 23514.0,
        "pnl": pnl,
        "stop_pts": stop,
        "target_pts": target,
        "bars_held": 4,
        "entry_index": 0,
        "exit_reason": exit_reason,
        "indicators": {
            "spot": 23500.0,
            "ema9": 23495.0,
            "ema21": 23480.0,
            "rsi": 64.0,
            "vwap": 23490.0,
            "volume_ratio": 1.4,
            "atr": 8.0,
            "index_stop_pts": stop,
            "index_target_pts": target,
        },
        "entry_validation": {
            "score": score,
            "verdict": "TAKE",
            "factors": {
                "ema_alignment": 1,
                "rsi_zone": 1,
                "vwap_position": 1,
                "volume": 1,
                "time_window": 1,
            },
        },
        "ai": {"regime": "TRENDING_BULL"},
    }


def _win_df():
    return pd.DataFrame(
        {
            "high": [23502.0, 23505.0, 23508.0, 23518.0, 23514.0],
            "low": [23498.0, 23499.0, 23500.0, 23506.0, 23510.0],
            "close": [23500.0, 23503.0, 23506.0, 23516.0, 23514.0],
        }
    )


def test_perfect_win_grade_a():
    out = reinforce_winning_trade(
        instrument_key="nifty50",
        trade=_win_trade(),
        regime="TRENDING_BULL",
        df=_win_df(),
    )
    assert out["trade_grade"] == "A"
    assert out["reinforce_pattern"] is True
    assert out["target_adjustment_suggestion"] == "wider"
    assert out["missed_profit_pts"] > 0
    assert out["pattern_tags"]


def test_partial_exit_grade_b():
    out = reinforce_winning_trade(
        instrument_key="nifty50",
        trade=_win_trade(exit_reason="ai_quick_exit", pnl=8, target=14),
        df=_win_df(),
    )
    assert out["trade_grade"] in ("B", "C")
    assert out["exit_type"] == "PARTIAL"


def test_lucky_win_grade_c():
    out = reinforce_winning_trade(
        instrument_key="nifty50",
        trade=_win_trade(score=2, pnl=5),
    )
    assert out["trade_grade"] == "C"
    assert out["reinforce_pattern"] is False


def test_skip_non_win():
    out = reinforce_winning_trade(
        instrument_key="nifty50",
        trade={**_win_trade(), "pnl": -5, "exit": 23493.0},
    )
    assert out.get("skipped") is True


def test_save_reinforcement():
    redis = _FakeRedis()
    out = reinforce_winning_trade(instrument_key="nifty50", trade=_win_trade(), df=_win_df())
    save_win_reinforcement(redis, 1, "nifty50", out)
    assert redis.get("scalping:desk:1:nifty50:win_reinforcements")
    assert redis.get("scalping:desk:1:nifty50:reinforced_tags")
