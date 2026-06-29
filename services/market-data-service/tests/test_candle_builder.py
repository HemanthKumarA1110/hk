from datetime import datetime, timezone

from app.engine.candle_builder import CandleBuilder


def test_candle_builder_rollover():
    builder = CandleBuilder(intervals={"1m": 1})
    ts = datetime(2026, 6, 29, 10, 0, 30, tzinfo=timezone.utc)
    builder.ingest("3045", "SBIN-EQ", 100, 10, ts)
    completed = builder.ingest("3045", "SBIN-EQ", 101, 5, datetime(2026, 6, 29, 10, 1, 5, tzinfo=timezone.utc))
    assert len(completed) == 1
    assert completed[0]["close"] == 100
