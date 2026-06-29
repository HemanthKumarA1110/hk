"""Enqueue backtest Celery jobs."""

from __future__ import annotations


def enqueue_backtest(run_id: int) -> None:
    from celery import Celery

    from trading_shared.config import get_settings

    settings = get_settings()
    app = Celery(broker=settings.REDIS_URL, backend=settings.REDIS_URL)
    app.send_task("backtest.run", args=[run_id])
