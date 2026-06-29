"""Angel One SmartWebSocketV2 streaming wrapper."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from SmartApi.smartWebSocketV2 import SmartWebSocketV2

from trading_shared.market.constants import NSE_CM, NSE_FO, SNAP_QUOTE_MODE

logger = logging.getLogger(__name__)


class AngelOneWebSocketStream:
    """Thread-based SmartWebSocketV2 client with tick callbacks."""

    def __init__(
        self,
        auth_token: str,
        api_key: str,
        client_code: str,
        feed_token: str,
        on_tick: Callable[[dict[str, Any]], None],
        max_retry_attempt: int = 5,
    ):
        self.auth_token = auth_token
        self.api_key = api_key
        self.client_code = client_code
        self.feed_token = feed_token
        self.on_tick = on_tick
        self._ws: SmartWebSocketV2 | None = None
        self._thread: threading.Thread | None = None
        self._connected = False
        self._subscriptions: list[dict[str, Any]] = []
        self._max_retry_attempt = max_retry_attempt

    @property
    def connected(self) -> bool:
        return self._connected

    def _build_ws(self) -> SmartWebSocketV2:
        ws = SmartWebSocketV2(
            self.auth_token,
            self.api_key,
            self.client_code,
            self.feed_token,
            max_retry_attempt=self._max_retry_attempt,
        )

        def on_open(_wsapp):
            self._connected = True
            logger.info("Angel One WebSocket connected")
            if self._subscriptions:
                ws.subscribe("tradingbot", SNAP_QUOTE_MODE, self._subscriptions)

        def on_data(_wsapp, data):
            try:
                self.on_tick(data)
            except Exception:
                logger.exception("Tick callback failed")

        def on_error(_wsapp, error):
            logger.error("Angel One WebSocket error: %s", error)
            self._connected = False

        def on_close(_wsapp):
            logger.warning("Angel One WebSocket closed")
            self._connected = False

        ws.on_open = on_open
        ws.on_data = on_data
        ws.on_error = on_error
        ws.on_close = on_close
        return ws

    def set_subscriptions(self, token_groups: list[dict[str, Any]]) -> None:
        self._subscriptions = token_groups

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._ws = self._build_ws()
        self._thread = threading.Thread(target=self._ws.connect, daemon=True, name="angel-ws")
        self._thread.start()

    def stop(self) -> None:
        if self._ws:
            self._ws.close_connection()
        self._connected = False

    @staticmethod
    def build_token_groups(
        nse_cm_tokens: list[str] | None = None,
        nse_fo_tokens: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        groups: list[dict[str, Any]] = []
        if nse_cm_tokens:
            groups.append({"exchangeType": NSE_CM, "tokens": nse_cm_tokens})
        if nse_fo_tokens:
            groups.append({"exchangeType": NSE_FO, "tokens": nse_fo_tokens})
        return groups
