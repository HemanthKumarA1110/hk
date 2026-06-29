from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.task_routes = {
    'app.tasks.worker.execute_trade': {'queue': 'trades'},
}

@celery_app.task
def execute_trade(order_payload: dict):
    # placeholder: call broker client to place order and persist result
    return {"status": "not_implemented"}
