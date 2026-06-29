import asyncio
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from trading_shared.broker.angel_one.exceptions import AngelOneAuthError

from trading_shared.db.session import SessionLocal, get_db, init_db
from trading_shared.middleware.auth import get_current_user
from trading_shared.models import User
from trading_shared.schemas.strategy import EngineSignalsResponse, StrategyRunResponse
from trading_shared.service_factory import create_service_app
from trading_shared.strategies.orchestrator import StrategyOrchestrator

logger = logging.getLogger(__name__)
app = create_service_app("strategy-engine", "Scalping, intraday, and swing strategy engines")
router = APIRouter(prefix="/api/v1/strategies", tags=["strategies"])

_runner_task: asyncio.Task | None = None


@router.post("/run", response_model=StrategyRunResponse)
def run_strategies(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    orchestrator = StrategyOrchestrator(db)
    return orchestrator.run_all()


@router.get("/scalping", response_model=EngineSignalsResponse)
def get_scalping_signals(_: User = Depends(get_current_user)) -> dict:
    return StrategyOrchestrator.get_cached("scalping")


@router.get("/intraday", response_model=EngineSignalsResponse)
def get_intraday_signals(_: User = Depends(get_current_user)) -> dict:
    from trading_shared.strategies.intraday_scanner import get_intraday_picks

    return get_intraday_picks()


@router.post("/intraday/scan", response_model=EngineSignalsResponse)
def scan_intraday_picks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.intraday_scanner import run_intraday_scan

    try:
        return run_intraday_scan(db, current_user.id, limit=10)
    except AngelOneAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Intraday scan failed for user_id=%s", current_user.id)
        raise HTTPException(status_code=500, detail=f"Intraday scan failed: {exc}") from exc


@router.get("/swing", response_model=EngineSignalsResponse)
def get_swing_signals(_: User = Depends(get_current_user)) -> dict:
    from trading_shared.strategies.swing_scanner import get_swing_picks

    return get_swing_picks()


@router.post("/swing/scan", response_model=EngineSignalsResponse)
def scan_swing_picks(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.swing_scanner import run_swing_scan

    try:
        return run_swing_scan(db, current_user.id, limit=10)
    except AngelOneAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Swing scan failed for user_id=%s", current_user.id)
        raise HTTPException(status_code=500, detail=f"Swing scan failed: {exc}") from exc


@router.get("/status")
def strategy_status(_: User = Depends(get_current_user)) -> dict:
    from trading_shared.strategies.intraday_scanner import get_intraday_picks
    from trading_shared.strategies.strategy_registry import ENGINE_REGISTRY, engine_configs
    from trading_shared.strategies.swing_scanner import get_swing_picks

    scalping = StrategyOrchestrator.get_cached("scalping")
    intraday = get_intraday_picks()
    swing = get_swing_picks()

    return {
        "engines": ["scalping", "intraday", "swing"],
        "scalping_min_score": ENGINE_REGISTRY["scalping"]["min_score"],
        "intraday_min_score": ENGINE_REGISTRY["intraday"]["min_score"],
        "swing_min_score": ENGINE_REGISTRY["swing"]["min_score"],
        "engine_configs": engine_configs(),
        "scalping": scalping,
        "intraday": intraday,
        "swing": swing,
    }


app.include_router(router)


def wait_for_db(retries: int = 20, delay_seconds: int = 2) -> None:
    for attempt in range(1, retries + 1):
        try:
            init_db()
            return
        except Exception:
            if attempt == retries:
                raise
            time.sleep(delay_seconds)


async def _ensure_scrip_master() -> None:
    import redis

    from trading_shared.config import get_settings
    from trading_shared.market.scrip_master import REDIS_SCRIP_KEY, ScripMasterService

    settings = get_settings()
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    scrip = ScripMasterService(redis_client)
    if scrip.ensure_loaded():
        return
    try:
        await scrip.refresh(force=True)
        logger.info("Scrip master bootstrapped for strategy-engine")
    except Exception:
        logger.exception("Failed to bootstrap scrip master; index lookups will use static fallbacks")


async def _strategy_loop() -> None:
    while True:
        try:
            db = SessionLocal()
            try:
                StrategyOrchestrator(db).run_all()
            finally:
                db.close()
        except Exception:
            logger.exception("Strategy loop failed")
        await asyncio.sleep(60)


@app.on_event("startup")
async def on_startup() -> None:
    global _runner_task
    wait_for_db()
    await _ensure_scrip_master()
    _runner_task = asyncio.create_task(_strategy_loop())
