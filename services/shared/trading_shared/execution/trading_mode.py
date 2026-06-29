"""Per-user trading mode (paper vs live) stored in Redis."""

from __future__ import annotations

import redis

MODE_PAPER = "paper"
MODE_LIVE = "live"
VALID_MODES = {MODE_PAPER, MODE_LIVE}


class TradingModeStore:
    def __init__(self, redis_url: str):
        self.client = redis.from_url(redis_url, decode_responses=True)

    def _key(self, user_id: int) -> str:
        return f"trading_mode:{user_id}"

    def get(self, user_id: int) -> str:
        value = self.client.get(self._key(user_id))
        return value if value in VALID_MODES else MODE_PAPER

    def set(self, user_id: int, mode: str) -> str:
        if mode not in VALID_MODES:
            raise ValueError(f"Invalid trading mode: {mode}")
        self.client.set(self._key(user_id), mode)
        return mode
