"""Scalping desk package."""

from trading_shared.strategies.scalping_desk.service import (
    ScalpingDeskService,
    run_desk_backtest,
    run_desk_evaluate,
)

__all__ = ["ScalpingDeskService", "run_desk_evaluate", "run_desk_backtest"]
