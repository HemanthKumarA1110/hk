"""Redis-backed rate limiting for auth and order endpoints."""

from __future__ import annotations

import redis

from trading_shared.config import get_settings


class RateLimiter:
    def __init__(self, redis_url: str | None = None):
        settings = get_settings()
        self.redis = redis.from_url(redis_url or settings.REDIS_URL, decode_responses=True)

    def allow(self, key: str, limit: int, window_seconds: int = 60) -> bool:
        bucket = f"ratelimit:{key}"
        current = self.redis.incr(bucket)
        if current == 1:
            self.redis.expire(bucket, window_seconds)
        return current <= limit
