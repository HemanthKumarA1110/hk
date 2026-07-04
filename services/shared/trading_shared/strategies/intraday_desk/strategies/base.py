"""Base intraday strategy interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class IntradaySignal:
    side: str  # BUY | SELL
    entry: float
    stoploss: float
    target: float
    trailing_pct: float | None = None
    strategy_id: str = ""
    strategy_code: str = ""


class IntradayStrategy(ABC):
    id: str = ""
    code: str = ""

    @abstractmethod
    def try_entry(self, df: pd.DataFrame, idx: int, traded_today: bool) -> IntradaySignal | None:
        """Return entry signal on bar idx, or None."""

    @abstractmethod
    def try_exit(self, position: dict, df: pd.DataFrame, idx: int) -> tuple[float, str] | None:
        """Return (exit_price, reason) if position should close."""

    def update_trailing(self, position: dict, row: pd.Series) -> None:
        trail_pct = position.get("trailing_pct")
        if not trail_pct:
            return
        if position["side"] == "BUY":
            trail = row["close"] * (1 - trail_pct / 100)
            position["stoploss"] = max(position["stoploss"], trail)
        else:
            trail = row["close"] * (1 + trail_pct / 100)
            position["stoploss"] = min(position["stoploss"], trail)
