"""Base swing strategy interface (long-only)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd


@dataclass
class SwingSignal:
    entry: float
    stoploss: float
    strategy_id: str = ""
    strategy_code: str = ""
    max_hold_days: int = 60
    trailing_pct: float | None = None
    use_chandelier: bool = False
    chandelier_atr_mult: float = 3.0


class SwingStrategy(ABC):
    id: str = ""
    code: str = ""
    max_hold_days: int = 60

    @abstractmethod
    def try_entry(self, df: pd.DataFrame, idx: int, in_position: bool) -> SwingSignal | None:
        """Return long entry signal on bar idx."""

    @abstractmethod
    def try_exit(self, position: dict, df: pd.DataFrame, idx: int) -> tuple[float, str] | None:
        """Return (exit_price, reason) if position should close."""

    def update_position(self, position: dict, row: pd.Series) -> None:
        close = float(row["close"])
        peak = max(float(position.get("peak_close") or position["entry_price"]), close)
        position["peak_close"] = peak

        if position.get("use_chandelier"):
            atr_val = float(row.get("atr14") or 0)
            if atr_val > 0:
                mult = float(position.get("chandelier_atr_mult") or 3.0)
                trail = peak - mult * atr_val
                position["stoploss"] = max(float(position["stoploss"]), trail)
            return

        trail_pct = position.get("trailing_pct")
        if trail_pct:
            trail = peak * (1 - float(trail_pct) / 100)
            position["stoploss"] = max(float(position["stoploss"]), trail)

    def _hold_days_exceeded(self, position: dict, idx: int) -> bool:
        entry_idx = int(position.get("entry_idx", idx))
        max_days = int(position.get("max_hold_days") or self.max_hold_days)
        return (idx - entry_idx) >= max_days

    def _stop_hit(self, position: dict, row: pd.Series) -> bool:
        return float(row["low"]) <= float(position["stoploss"])
