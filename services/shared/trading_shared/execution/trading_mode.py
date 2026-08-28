"""Per-user trading mode. Live Angel One orders only — paper execution is retired."""

from __future__ import annotations

import redis

MODE_LIVE = "live"
MODE_PAPER = "paper"  # kept for legacy comparisons; store always returns live
VALID_MODES = {MODE_LIVE}


class TradingModeStore:
    def __init__(self, redis_url: str):
        self.client = redis.from_url(redis_url, decode_responses=True)

    def _key(self, user_id: int) -> str:
        return f"trading_mode:{user_id}"

    def get(self, user_id: int) -> str:
        self.client.set(self._key(user_id), MODE_LIVE)
        return MODE_LIVE

    def set(self, user_id: int, mode: str) -> str:
        del mode
        self.client.set(self._key(user_id), MODE_LIVE)
        return MODE_LIVE
