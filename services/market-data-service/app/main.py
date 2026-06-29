import asyncio
import logging
import time

from trading_shared.config import get_settings
from trading_shared.db.session import init_db
from trading_shared.service_factory import create_service_app, register_ready_health

from app.api.routes.market import router as market_router
from app.engine.stream_manager import StreamManager

logger = logging.getLogger(__name__)
settings = get_settings()

app = create_service_app("market-data-service", "Live and historical market data for NSE/BSE")
register_ready_health(app, "market-data-service", redis_required=True)
app.include_router(market_router)


def wait_for_db(retries: int = 20, delay_seconds: int = 2) -> None:
    for attempt in range(1, retries + 1):
        try:
            init_db()
            return
        except Exception:
            if attempt == retries:
                raise
            time.sleep(delay_seconds)


@app.on_event("startup")
async def on_startup() -> None:
    wait_for_db()
    asyncio.create_task(_auto_start_stream())


async def _auto_start_stream() -> None:
    await asyncio.sleep(5)
    try:
        status = await StreamManager.get().start()
        logger.info("Auto-started market stream: %s", status)
    except Exception:
        logger.exception("Failed to auto-start market stream")
