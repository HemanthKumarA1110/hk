"""Live 1-second scalping desk runner — tick-aware, background, no UI required."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

import redis
from sqlalchemy.orm import Session

from trading_shared.config import get_settings
from trading_shared.db.session import SessionLocal
from trading_shared.market.constants import BANKNIFTY_INDEX_TOKEN, NIFTY_INDEX_TOKEN, PUBSUB_TICKS
from trading_shared.market.redis_bus import MarketRedisBus
from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS
from trading_shared.strategies.scalping_desk.service import iter_auto_enabled_desks, run_scalping_desk_auto_sync

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")
INDEX_TOKEN_TO_INSTRUMENT = {
    NIFTY_INDEX_TOKEN: "nifty50",
    BANKNIFTY_INDEX_TOKEN: "banknifty",
}


class ScalpingStreamRunner:
    """Evaluate Nifty / Bank Nifty scalping desks every second using live Redis ticks."""

    def __init__(self, redis_url: str | None = None, interval_sec: float | None = None):
        settings = get_settings()
        self.redis_url = redis_url or settings.REDIS_URL
        self.interval_sec = max(
            0.5,
            float(interval_sec if interval_sec is not None else getattr(settings, "SCALPING_STREAM_INTERVAL_SEC", 1.0)),
        )
        self._last_eval: dict[str, float] = {}
        self._running = False
        self._tick_wake = asyncio.Event()
        self._pending_instruments: set[str] = set()

    def _throttle_key(self, user_id: int, instrument_key: str) -> str:
        return f"{user_id}:{instrument_key}"

    def _should_eval(self, user_id: int, instrument_key: str) -> bool:
        key = self._throttle_key(user_id, instrument_key)
        now = time.monotonic()
        last = self._last_eval.get(key, 0.0)
        if now - last < self.interval_sec:
            return False
        self._last_eval[key] = now
        return True

    @staticmethod
    def _in_market_session() -> bool:
        now = datetime.now(IST)
        if now.weekday() >= 5:
            return False
        minutes = now.hour * 60 + now.minute
        return 9 * 60 + 14 <= minutes <= 15 * 60 + 16

    def _eval_sync(self, user_id: int, instrument_key: str) -> dict[str, Any]:
        db: Session = SessionLocal()
        try:
            return run_scalping_desk_auto_sync(db, user_id, instrument_key, stream_cycle=True)
        except Exception as exc:
            logger.exception(
                "Scalping stream eval failed user_id=%s instrument=%s",
                user_id,
                instrument_key,
            )
            return {"errors": [str(exc)], "instrument": instrument_key}
        finally:
            db.close()

    async def _eval_desk(self, user_id: int, instrument_key: str) -> dict[str, Any] | None:
        if not self._should_eval(user_id, instrument_key):
            return None
        return await asyncio.to_thread(self._eval_sync, user_id, instrument_key)

    async def _run_enabled_desks(self, instrument_filter: set[str] | None = None) -> None:
        desks = iter_auto_enabled_desks(self.redis_url)
        if not desks:
            return
        tasks = []
        for user_id, instrument_key in desks:
            if instrument_filter and instrument_key not in instrument_filter:
                continue
            tasks.append(self._eval_desk(user_id, instrument_key))
        if tasks:
            await asyncio.gather(*tasks)

    async def _interval_loop(self) -> None:
        while self._running:
            try:
                if self._in_market_session():
                    await self._run_enabled_desks()
            except Exception:
                logger.exception("Scalping stream interval loop failed")
            await asyncio.sleep(self.interval_sec)

    async def _tick_loop(self) -> None:
        while self._running:
            await self._tick_wake.wait()
            self._tick_wake.clear()
            if not self._in_market_session():
                self._pending_instruments.clear()
                continue
            instruments = set(self._pending_instruments)
            self._pending_instruments.clear()
            if instruments:
                await self._run_enabled_desks(instrument_filter=instruments)

    def _on_tick_message(self, raw: str) -> None:
        try:
            tick = json.loads(raw)
        except json.JSONDecodeError:
            return
        instrument_key = INDEX_TOKEN_TO_INSTRUMENT.get(str(tick.get("token") or ""))
        if not instrument_key:
            return
        self._pending_instruments.add(instrument_key)
        loop = getattr(self, "_loop", None)
        if loop and loop.is_running():
            loop.call_soon_threadsafe(self._tick_wake.set)

    def _pubsub_thread(self) -> None:
        client = redis.from_url(self.redis_url, decode_responses=True)
        pubsub = client.pubsub()
        pubsub.subscribe(PUBSUB_TICKS)
        while self._running:
            message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if not message or message.get("type") != "message":
                continue
            data = message.get("data")
            if isinstance(data, str):
                self._on_tick_message(data)

    async def run(self) -> None:
        self._running = True
        self._loop = asyncio.get_running_loop()
        logger.info(
            "Scalping stream runner started — interval=%.2fs instruments=%s",
            self.interval_sec,
            list(INSTRUMENTS.keys()),
        )
        pubsub = threading.Thread(target=self._pubsub_thread, name="scalping-tick-pubsub", daemon=True)
        pubsub.start()
        await asyncio.gather(self._interval_loop(), self._tick_loop())

    def stop(self) -> None:
        self._running = False
        self._tick_wake.set()


async def run_scalping_stream_forever() -> None:
    runner = ScalpingStreamRunner()
    await runner.run()
