"""Deep health checks for Postgres and Redis."""

from __future__ import annotations

import redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from trading_shared.config import get_settings


def check_postgres(db: Session | None = None) -> dict:
    if db is None:
        return {"status": "skipped"}
    try:
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def check_redis() -> dict:
    settings = get_settings()
    try:
        client = redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        client.ping()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


def build_health(service: str, db: Session | None = None, redis_required: bool = False) -> dict:
    settings = get_settings()
    payload = {
        "status": "ok",
        "service": service,
        "env": settings.ENV,
    }
    if db is not None:
        db_status = check_postgres(db)
        payload["database"] = db_status
        if db_status["status"] != "ok":
            payload["status"] = "degraded"
    if redis_required:
        redis_status = check_redis()
        payload["redis"] = redis_status
        if redis_status["status"] != "ok":
            payload["status"] = "degraded"
    return payload
