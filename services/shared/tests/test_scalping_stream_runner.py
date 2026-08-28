import asyncio
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


def test_stream_runner_skips_inflight_eval():
    runner = ScalpingStreamRunner(redis_url="redis://test", interval_sec=0.5)
    runner._last_eval.clear()
    runner._inflight.add("1:banknifty")

    async def _run():
        return await runner._eval_desk(1, "banknifty")

    assert asyncio.run(_run()) is None
