import time

from trading_shared.strategies.scalping_desk.stream_runner import ScalpingStreamRunner


def test_stream_runner_throttles_per_desk():
    runner = ScalpingStreamRunner(redis_url="redis://test", interval_sec=1.0)
    assert runner._should_eval(1, "nifty50") is True
    assert runner._should_eval(1, "nifty50") is False
    runner._last_eval["1:nifty50"] = time.monotonic() - 2.0
    assert runner._should_eval(1, "nifty50") is True


def test_stream_runner_allows_parallel_instruments():
    runner = ScalpingStreamRunner(redis_url="redis://test", interval_sec=1.0)
    assert runner._should_eval(1, "nifty50") is True
    assert runner._should_eval(1, "banknifty") is True
