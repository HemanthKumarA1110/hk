"""Historical data provider that replays OHLCV bars for strategy engines."""

from __future__ import annotations

import pandas as pd

from trading_shared.strategies.types import StrategySignalCandidate


class HistoricalDataProvider:
    """Drop-in replacement for StrategyDataProvider during bar replay."""

    def __init__(self, df: pd.DataFrame, token: str, symbol: str):
        self._df = df.reset_index(drop=True)
        self._token = token
        self._symbol = symbol
        self._current_idx = 0
        self._scan_hits: list[dict] = []
        self._sector_strength: dict[str, float] = {}
        self._option_chain: dict = {}

    def set_index(self, idx: int) -> None:
        self._current_idx = max(0, min(idx, len(self._df) - 1))

    def set_scan_hits(self, hits: list[dict]) -> None:
        self._scan_hits = hits

    def set_sector_strength(self, sectors: dict[str, float]) -> None:
        self._sector_strength = sectors

    def set_option_chain(self, chain: dict) -> None:
        self._option_chain = chain

    def tick(self, token: str, exchange_type: int = 1) -> dict | None:
        if self._current_idx < 0 or self._current_idx >= len(self._df):
            return None
        row = self._df.iloc[self._current_idx]
        return {
            "ltp": float(row["close"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume", 0)),
        }

    def candle(self, token: str, interval: str) -> dict | None:
        tick = self.tick(token)
        if not tick:
            return None
        ts = self._df.iloc[self._current_idx].get("timestamp", "")
        return {
            "open": tick["open"],
            "high": tick["high"],
            "low": tick["low"],
            "close": tick["close"],
            "volume": tick["volume"],
            "candle_ts": str(ts),
        }

    def scan_hits(self) -> list[dict]:
        return self._scan_hits

    def sector_strength(self) -> dict[str, float]:
        return self._sector_strength

    def option_chain(self, underlying: str) -> dict | None:
        if self._option_chain:
            return self._option_chain
        row = self._df.iloc[self._current_idx] if len(self._df) else None
        close = float(row["close"]) if row is not None else 24000
        return {
            "underlying": underlying,
            "pcr": 1.0,
            "rows": [
                {"symbol": f"{underlying}CE", "strike": close, "oi": 1000, "volume": 500},
                {"symbol": f"{underlying}PE", "strike": close, "oi": 1200, "volume": 600},
            ],
        }

    def build_intraday_frame(self, token: str, symbol: str, bars: int = 60) -> pd.DataFrame:
        start = max(0, self._current_idx - bars + 1)
        slice_df = self._df.iloc[start : self._current_idx + 1].copy()
        if slice_df.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        slice_df["symbol"] = symbol
        return slice_df.reset_index(drop=True)

    def build_daily_frame(self, token: str, symbol: str, days: int = 120) -> pd.DataFrame:
        available = self._df.iloc[: self._current_idx + 1].copy()
        if available.empty:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        if "timestamp" in available.columns:
            available["timestamp"] = pd.to_datetime(available["timestamp"], errors="coerce")
            daily = (
                available.set_index("timestamp")
                .resample("1D")
                .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
                .dropna(subset=["close"])
            )
            daily = daily.tail(days).reset_index(drop=True)
        else:
            daily = available.tail(min(days, len(available))).reset_index(drop=True)

        daily["symbol"] = symbol
        return daily

    def nifty_universe(self) -> list[tuple[str, str]]:
        return [(self._token, self._symbol)]

    def index_tokens(self) -> dict[str, tuple[str, str]]:
        name = self._symbol.replace("-EQ", "").replace("EQ", "").split("-")[0]
        if name in ("NIFTY", "BANKNIFTY"):
            return {name: (self._token, self._symbol)}
        return {"NIFTY": (self._token, self._symbol)}


def evaluate_engine(engine: str, provider: HistoricalDataProvider) -> list[StrategySignalCandidate]:
    from trading_shared.strategies.intraday_engine import IntradayEngine
    from trading_shared.strategies.scalping_engine import ScalpingEngine
    from trading_shared.strategies.swing_engine import SwingEngine

    if engine == "scalping":
        return ScalpingEngine(provider).evaluate()
    if engine == "intraday":
        return IntradayEngine(provider).evaluate(limit=1)
    if engine == "swing":
        return SwingEngine(provider).evaluate(limit=1)
    raise ValueError(f"Unknown engine: {engine}")
