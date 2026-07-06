"""Scalping desk package."""

from trading_shared.strategies.scalping_desk.service import (
    ScalpingDeskService,
    iter_auto_enabled_desks,
    run_desk_backtest,
    run_desk_evaluate,
    run_scalping_desk_auto_sync,
)
from trading_shared.strategies.scalping_desk.stream_runner import ScalpingStreamRunner

__all__ = [
    "ScalpingDeskService",
    "ScalpingStreamRunner",
    "iter_auto_enabled_desks",
    "run_desk_evaluate",
    "run_desk_backtest",
    "run_scalping_desk_auto_sync",
]
