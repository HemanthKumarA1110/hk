"""Redis pub/sub and key-value helpers for market data."""

from __future__ import annotations

import json
from typing import Any

import redis

from trading_shared.market.constants import (
    PUBSUB_OPTION_CHAIN,
    PUBSUB_SCAN,
    PUBSUB_TICKS,
    REDIS_CANDLE_PREFIX,
    REDIS_OPTION_CHAIN_PREFIX,
    REDIS_SCAN_KEY,
    REDIS_SECTOR_STRENGTH_KEY,
    REDIS_STREAM_STATUS_KEY,
    REDIS_TICK_PREFIX,
)


class MarketRedisBus:
    def __init__(self, redis_url: str):
        self.client = redis.from_url(redis_url, decode_responses=True)
        self.pubsub = self.client.pubsub()

    def store_tick(self, exchange_type: int | str, token: str, payload: dict[str, Any], ttl: int = 3600) -> None:
        key = f"{REDIS_TICK_PREFIX}:{exchange_type}:{token}"
        self.client.setex(key, ttl, json.dumps(payload))

    def get_tick(self, exchange_type: int | str, token: str) -> dict[str, Any] | None:
        raw = self.client.get(f"{REDIS_TICK_PREFIX}:{exchange_type}:{token}")
        return json.loads(raw) if raw else None

    def publish_tick(self, payload: dict[str, Any]) -> None:
        self.client.publish(PUBSUB_TICKS, json.dumps(payload))

    def store_candle(self, token: str, interval: str, payload: dict[str, Any], ttl: int = 86400) -> None:
        key = f"{REDIS_CANDLE_PREFIX}:{token}:{interval}"
        self.client.setex(key, ttl, json.dumps(payload))

    def get_candle(self, token: str, interval: str) -> dict[str, Any] | None:
        raw = self.client.get(f"{REDIS_CANDLE_PREFIX}:{token}:{interval}")
        return json.loads(raw) if raw else None

    def store_scan_results(self, payload: dict[str, Any], ttl: int = 120) -> None:
        self.client.setex(REDIS_SCAN_KEY, ttl, json.dumps(payload))
        self.client.publish(PUBSUB_SCAN, json.dumps(payload))

    def get_scan_results(self) -> dict[str, Any] | None:
        raw = self.client.get(REDIS_SCAN_KEY)
        return json.loads(raw) if raw else None

    def store_option_chain(self, underlying: str, payload: dict[str, Any], ttl: int = 120) -> None:
        key = f"{REDIS_OPTION_CHAIN_PREFIX}:{underlying}"
        self.client.setex(key, ttl, json.dumps(payload))
        self.client.publish(PUBSUB_OPTION_CHAIN, json.dumps(payload))

    def get_option_chain(self, underlying: str) -> dict[str, Any] | None:
        raw = self.client.get(f"{REDIS_OPTION_CHAIN_PREFIX}:{underlying}")
        return json.loads(raw) if raw else None

    def store_sector_strength(self, payload: dict[str, Any], ttl: int = 120) -> None:
        self.client.setex(REDIS_SECTOR_STRENGTH_KEY, ttl, json.dumps(payload))

    def get_sector_strength(self) -> dict[str, float] | None:
        raw = self.client.get(REDIS_SECTOR_STRENGTH_KEY)
        return json.loads(raw) if raw else None

    def store_stream_status(self, payload: dict[str, Any], ttl: int = 30) -> None:
        self.client.setex(REDIS_STREAM_STATUS_KEY, ttl, json.dumps(payload))

    def get_stream_status(self) -> dict[str, Any] | None:
        raw = self.client.get(REDIS_STREAM_STATUS_KEY)
        return json.loads(raw) if raw else None

    def subscribe(self, *channels: str) -> redis.client.PubSub:
        self.pubsub.subscribe(*channels)
        return self.pubsub
