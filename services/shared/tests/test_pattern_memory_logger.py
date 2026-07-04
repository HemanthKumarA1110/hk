from trading_shared.strategies.scalping_desk.pattern_memory_logger import (
    find_similar_patterns,
    log_trade_pattern,
    match_signal_to_memory,
    save_pattern_memory,
)


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, _ttl, value):
        self.store[key] = value


def _closed_trade(pnl=14, score=5, regime="TRENDING_BULL"):
    return {
        "timestamp": "2026-06-02T10:05:00+05:30",
        "entry_time": "2026-06-02T10:05:00+05:30",
        "signal_type": "CALL",
        "strategy_id": "ema_crossover_rsi",
        "entry": 120.0,
        "entry_spot": 23500.0,
        "exit": 23514.0,
        "pnl": pnl,
        "stop_pts": 7.0,
        "target_pts": 14.0,
        "indicators": {
            "spot": 23500.0,
            "ema9": 23495.0,
            "ema21": 23480.0,
            "rsi": 64.0,
            "vwap": 23490.0,
            "volume_ratio": 1.35,
            "open": 23498.0,
            "high": 23502.0,
            "low": 23496.0,
            "close": 23500.0,
        },
        "entry_validation": {"score": score, "verdict": "TAKE"},
        "ai": {"regime": regime},
    }


def test_winning_trade_pattern():
    out = log_trade_pattern(instrument_key="nifty50", trade=_closed_trade())
    assert out["outcome"] == "win"
    assert out["pattern_id"]
    assert len(out["setup_fingerprint"].split()) <= 20
    assert out["conditions"]["ema_aligned"] is True
    assert out["conditions"]["above_vwap"] is True
    assert out["recommendation"] in ("take", "take_with_reduced_size")
    assert out["edge_score"] >= 50


def test_losing_weak_trade_avoid():
    out = log_trade_pattern(
        instrument_key="nifty50",
        trade=_closed_trade(pnl=-7, score=2),
    )
    assert out["outcome"] == "loss"
    assert out["recommendation"] == "avoid"
    assert out["edge_score"] < 50


def test_pattern_id_stable():
    a = log_trade_pattern(instrument_key="nifty50", trade=_closed_trade())
    b = log_trade_pattern(instrument_key="nifty50", trade=_closed_trade())
    assert a["pattern_id"] == b["pattern_id"]


def test_find_similar_patterns():
    first = log_trade_pattern(instrument_key="nifty50", trade=_closed_trade())
    second = log_trade_pattern(instrument_key="nifty50", trade=_closed_trade(pnl=-7), history=[first])
    matches = find_similar_patterns([first, second], first["conditions"], direction="LONG")
    assert len(matches) >= 1


def test_save_pattern_memory():
    redis = _FakeRedis()
    pattern = log_trade_pattern(instrument_key="nifty50", trade=_closed_trade())
    save_pattern_memory(redis, 1, "nifty50", pattern)
    raw = redis.get("scalping:desk:1:nifty50:pattern_memory")
    assert raw
    assert "pattern_id" in raw


def test_match_signal_to_memory():
    stored = log_trade_pattern(instrument_key="nifty50", trade=_closed_trade())
    trade = _closed_trade()
    signal = {
        "signal_type": trade["signal_type"],
        "indicators": trade["indicators"],
        "timestamp": trade["timestamp"],
    }
    match = match_signal_to_memory(signal, [stored], regime="TRENDING_BULL")
    assert match["matched"] is True
    assert match["similar_count"] >= 1
