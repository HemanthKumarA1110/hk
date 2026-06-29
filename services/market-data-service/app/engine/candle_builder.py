"""Build OHLC candles from live ticks."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _bucket_ts(ts: datetime, interval_minutes: int) -> datetime:
    minute = (ts.minute // interval_minutes) * interval_minutes
    return ts.replace(minute=minute, second=0, microsecond=0)


@dataclass
class CandleState:
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    volume: float = 0.0
    pv_sum: float = 0.0
    bucket: datetime | None = None

    def update(self, price: float, volume: float, ts: datetime) -> None:
        if self.bucket is None:
            self.open = self.high = self.low = self.close = price
            self.volume = volume
            self.pv_sum = price * volume
            self.bucket = ts
            return
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.volume += volume
        self.pv_sum += price * volume

    def vwap(self) -> float | None:
        if self.volume <= 0:
            return None
        return round(self.pv_sum / self.volume, 2)

    def to_dict(self, token: str, symbol: str, interval: str) -> dict:
        return {
            "token": token,
            "symbol": symbol,
            "interval": interval,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "vwap": self.vwap(),
            "candle_ts": self.bucket.isoformat() if self.bucket else datetime.now(timezone.utc).isoformat(),
        }


@dataclass
class CandleBuilder:
    intervals: dict[str, int] = field(default_factory=lambda: {"1m": 1, "3m": 3, "5m": 5})
    _states: dict[tuple[str, str], CandleState] = field(default_factory=dict)

    def ingest(self, token: str, symbol: str, price: float, volume: float, ts: datetime | None = None) -> list[dict]:
        ts = ts or datetime.now(timezone.utc)
        completed: list[dict] = []
        for label, minutes in self.intervals.items():
            key = (token, label)
            bucket = _bucket_ts(ts, minutes)
            state = self._states.get(key)
            if state is None:
                state = CandleState(bucket=bucket)
                state.update(price, volume, bucket)
                self._states[key] = state
                continue
            if state.bucket != bucket:
                completed.append(state.to_dict(token, symbol, label))
                state = CandleState(bucket=bucket)
                state.update(price, volume, bucket)
                self._states[key] = state
            else:
                state.update(price, volume, bucket)
        return completed
