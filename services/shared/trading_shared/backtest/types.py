from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class BacktestTrade:
    entry_ts: str
    exit_ts: str
    side: str
    symbol: str
    entry_price: float
    exit_price: float
    qty: int
    pnl: float
    return_pct: float
    stoploss: float
    target: float
    exit_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
