from celery import Celery

from trading_shared.config import get_settings

settings = get_settings()

celery_app = Celery(
    "trading_bot",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "market-scanner-every-minute": {
            "task": "market.run_scanner",
            "schedule": 60.0,
        },
        "strategy-run-every-minute": {
            "task": "strategies.run_all",
            "schedule": 60.0,
        },
        "ai-evaluate-every-minute": {
            "task": "ai.evaluate_all",
            "schedule": 60.0,
        },
        "auto-trading-every-minute": {
            "task": "auto_trading.run",
            "schedule": 75.0,
        },
        "intraday-desk-every-minute": {
            "task": "intraday_desk.run",
            "schedule": 60.0,
        },
        "swing-desk-every-minute": {
            "task": "swing_desk.run",
            "schedule": 60.0,
        },
    },
)
