import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from trading_shared.broker.angel_one.exceptions import AngelOneAuthError
from trading_shared.broker.angel_one.schemas import LTPRequest, SearchScripRequest
from trading_shared.broker.angel_one.session_manager import AngelOneSessionManager
from trading_shared.config import get_settings
from trading_shared.db.session import get_db
from trading_shared.market.constants import PUBSUB_OPTION_CHAIN, PUBSUB_SCAN, PUBSUB_TICKS
from trading_shared.middleware.auth import get_current_user, require_roles
from trading_shared.models import User, UserRole
from trading_shared.schemas.market import IndexQuotesResponse, OptionChainResponse, ScanResponse, StreamStatusResponse, TickSnapshot

from trading_shared.market.redis_bus import MarketRedisBus
from app.engine.stream_manager import StreamManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/market", tags=["market"])
settings = get_settings()


def get_stream_manager() -> StreamManager:
    return StreamManager.get()


def get_redis_bus() -> MarketRedisBus:
    return MarketRedisBus(settings.REDIS_URL)


@router.get("/indices")
def list_indices() -> dict:
    from trading_shared.broker.angel_one.constants import INDEX_TOKENS

    return {"indices": INDEX_TOKENS}


@router.get("/indices/live", response_model=IndexQuotesResponse)
async def live_indices(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from datetime import datetime, timezone

    import redis

    from trading_shared.broker.angel_one.constants import INDEX_TOKENS
    from trading_shared.market.index_quotes import parse_ltp_payload, quote_from_tick

    bus = get_redis_bus()
    manager = AngelOneSessionManager(db, redis.from_url(settings.REDIS_URL, decode_responses=True))
    client = None
    quotes: list[dict] = []

    for name, meta in INDEX_TOKENS.items():
        token = str(meta["symboltoken"])
        cached = bus.get_tick(1, token)
        if cached:
            quotes.append(quote_from_tick(name, meta, cached, source="live_cache"))
            continue

        if client is None:
            try:
                client = await manager.get_client_for_user(current_user.id)
            except AngelOneAuthError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            response = await client.get_ltp(
                LTPRequest(
                    exchange=meta["exchange"],
                    tradingsymbol=meta["tradingsymbol"],
                    symboltoken=token,
                )
            )
            quotes.append(parse_ltp_payload(name, meta, response))
        except Exception as exc:
            logger.warning("Index LTP fetch failed for %s: %s", name, exc)
            quotes.append(
                {
                    "name": name,
                    "label": meta.get("tradingsymbol", name),
                    "symboltoken": token,
                    "exchange": meta.get("exchange"),
                    "ltp": None,
                    "source": "broker_api",
                    "error": str(exc),
                }
            )

    return {"generated_at": datetime.now(timezone.utc).isoformat(), "indices": quotes}


@router.get("/ltp")
async def get_ltp(
    exchange: str = Query(..., examples=["NSE"]),
    tradingsymbol: str = Query(..., examples=["SBIN-EQ"]),
    symboltoken: str = Query(..., examples=["3045"]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    bus = get_redis_bus()
    cached = bus.get_tick(1, symboltoken)
    if cached:
        return {"status": True, "source": "live_cache", "data": cached}

    manager = AngelOneSessionManager(db)
    try:
        client = await manager.get_client_for_user(current_user.id)
        return await client.get_ltp(
            LTPRequest(exchange=exchange, tradingsymbol=tradingsymbol, symboltoken=symboltoken)
        )
    except AngelOneAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/search")
async def search_scrip(
    exchange: str = Query(...),
    searchscrip: str = Query(..., min_length=2),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    manager = AngelOneSessionManager(db)
    try:
        client = await manager.get_client_for_user(current_user.id)
        return await client.search_scrip(SearchScripRequest(exchange=exchange, searchscrip=searchscrip))
    except AngelOneAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/tick/{exchange_type}/{token}", response_model=TickSnapshot)
def get_cached_tick(exchange_type: int, token: str, _: User = Depends(get_current_user)) -> dict:
    bus = get_redis_bus()
    tick = bus.get_tick(exchange_type, token)
    if not tick:
        raise HTTPException(status_code=404, detail="Tick not available")
    return tick


@router.get("/candles/{token}")
def get_cached_candles(
    token: str,
    interval: str = Query("1m", pattern="^(1m|3m|5m)$"),
    _: User = Depends(get_current_user),
) -> dict:
    bus = get_redis_bus()
    candle = bus.get_candle(token, interval)
    if not candle:
        raise HTTPException(status_code=404, detail="Candle not available")
    return candle


@router.get("/historical")
async def historical_candles(
    exchange: str = Query("NSE"),
    symboltoken: str = Query(...),
    interval: str = Query("1m"),
    fromdate: str = Query(..., description="YYYY-MM-DD HH:MM"),
    todate: str = Query(..., description="YYYY-MM-DD HH:MM"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    manager = StreamManager.get()
    return await manager.fetch_historical_candles(
        db, current_user.id, exchange, symboltoken, interval, fromdate, todate
    )


@router.get("/scan/latest", response_model=ScanResponse)
def latest_scan(_: User = Depends(get_current_user)) -> dict:
    bus = get_redis_bus()
    payload = bus.get_scan_results()
    if not payload:
        return {"generated_at": "", "hits": [], "sector_strength": {}}
    return payload


@router.post("/scan/run")
def run_scan_now(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
) -> dict:
    manager = StreamManager.get()
    return manager.scanner.run_scan(db)


@router.get("/sector/strength")
def sector_strength(_: User = Depends(get_current_user)) -> dict:
    bus = get_redis_bus()
    return {"sector_strength": bus.get_sector_strength() or {}}


@router.get("/option-chain/{underlying}", response_model=OptionChainResponse)
def option_chain(underlying: str, _: User = Depends(get_current_user)) -> dict:
    bus = get_redis_bus()
    payload = bus.get_option_chain(underlying.upper())
    if not payload:
        return {
            "underlying": underlying.upper(),
            "expiry": "",
            "spot": 0,
            "pcr": None,
            "total_ce_oi": 0,
            "total_pe_oi": 0,
            "rows": [],
        }
    return payload


@router.get("/stream/status", response_model=StreamStatusResponse)
def stream_status(_: User = Depends(get_current_user)) -> dict:
    bus = get_redis_bus()
    cached = bus.get_stream_status()
    if cached:
        return cached
    return StreamManager.get().status()


@router.post("/stream/start")
async def start_stream(_: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER))) -> dict:
    return await StreamManager.get().start()


@router.post("/stream/stop")
async def stop_stream(_: User = Depends(require_roles(UserRole.ADMIN))) -> dict:
    return await StreamManager.get().stop()


@router.websocket("/ws")
async def market_ws(websocket: WebSocket):
    await websocket.accept()
    bus = get_redis_bus()
    pubsub = bus.subscribe(PUBSUB_TICKS, PUBSUB_SCAN, PUBSUB_OPTION_CHAIN)

    async def relay():
        while True:
            message = await asyncio.to_thread(pubsub.get_message, True, 1.0)
            if message and message.get("data"):
                await websocket.send_text(message["data"])
            await asyncio.sleep(0.01)

    try:
        await relay()
    except WebSocketDisconnect:
        logger.info("Market websocket disconnected")
    finally:
        pubsub.close()
