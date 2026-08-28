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


def _validate_desk_instrument(instrument: str) -> str:
    from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

    key = instrument.lower()
    if key not in INSTRUMENTS:
        raise HTTPException(status_code=404, detail=f"Unknown instrument: {instrument}")
    return key


@router.get("/scalping/desk/{instrument}/strategies")
def list_scalping_strategies(
    instrument: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import ScalpingDeskService
    from trading_shared.strategies.scalping_desk.strategy_catalog import CATALOG_VERSION, catalog_for_api
    from trading_shared.strategies.scalping_desk.strategy_selector import all_strategy_families
    from trading_shared.strategies.strategy_code_validation import filter_catalog_for_engine

    key = _validate_desk_instrument(instrument)
    service = ScalpingDeskService(db, current_user.id, key)
    config = service.get_config()
    return {
        "strategies": filter_catalog_for_engine("scalping", catalog_for_api(key, config)),
        "families": all_strategy_families(),
        "catalog_version": CATALOG_VERSION,
        "desk": "scalping",
    }


@router.get("/scalping/desk/{instrument}")
def get_scalping_desk(
    instrument: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import run_desk_snapshot

    key = _validate_desk_instrument(instrument)
    return run_desk_snapshot(db, current_user.id, key)


@router.post("/scalping/desk/{instrument}/evaluate")
def evaluate_scalping_desk(
    instrument: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import run_desk_evaluate

    key = _validate_desk_instrument(instrument)
    try:
        return run_desk_evaluate(db, current_user.id, key)
    except AngelOneAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/scalping/desk/{instrument}/config")
def update_scalping_desk_config(
    instrument: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import ScalpingDeskService

    key = _validate_desk_instrument(instrument)
    service = ScalpingDeskService(db, current_user.id, key)
    config = {**service.get_config(), **payload}
    return service.save_config(config)


@router.post("/scalping/desk/{instrument}/auto-trading")
def toggle_scalping_auto_trading(
    instrument: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import ScalpingDeskService

    key = _validate_desk_instrument(instrument)
    service = ScalpingDeskService(db, current_user.id, key)
    return service.toggle_auto_trading(bool(payload.get("enabled")))


@router.post("/scalping/desk/{instrument}/close-active")
def close_active_scalping_trade(
    instrument: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import run_desk_emergency_close

    key = _validate_desk_instrument(instrument)
    try:
        return run_desk_emergency_close(db, current_user.id, key)
    except AngelOneAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Emergency close failed for user_id=%s instrument=%s", current_user.id, key)
        raise HTTPException(status_code=500, detail=f"Emergency close failed: {exc}") from exc


@router.post("/scalping/desk/{instrument}/backtest")
def backtest_scalping_desk(
    instrument: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import queue_desk_backtest_job

    key = _validate_desk_instrument(instrument)
    try:
        return queue_desk_backtest_job(current_user.id, key, payload)
    except AngelOneAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Scalping backtest queue failed for user_id=%s instrument=%s", current_user.id, key)
        raise HTTPException(status_code=500, detail=f"Backtest failed: {exc}") from exc


@router.get("/scalping/desk/{instrument}/backtest/{job_id}")
def desk_backtest_job_status(
    instrument: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import fetch_desk_backtest_job

    _validate_desk_instrument(instrument)
    return fetch_desk_backtest_job(current_user.id, job_id)


@router.post("/scalping/desk/{instrument}/optimize")
def optimize_scalping_desk(
    instrument: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import ScalpingDeskService

    key = _validate_desk_instrument(instrument)
    service = ScalpingDeskService(db, current_user.id, key)
    summary = payload.get("backtest_summary") or payload
    return service.optimize_from_backtest(summary)


@router.post("/scalping/desk/{instrument}/eod-review")
def eod_review_scalping_desk(
    instrument: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import run_desk_eod_review

    key = _validate_desk_instrument(instrument)
    return run_desk_eod_review(db, current_user.id, key)


@router.post("/scalping/desk/{instrument}/weekly-tune")
def weekly_tune_scalping_desk(
    instrument: str,
    payload: dict | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import run_desk_weekly_tune

    key = _validate_desk_instrument(instrument)
    body = payload or {}
    return run_desk_weekly_tune(
        db,
        current_user.id,
        key,
        apply=bool(body.get("apply")),
        days=int(body.get("days") or 5),
    )


@router.get("/scalping/desk/{instrument}/pattern-memory")
def pattern_memory_scalping_desk(
    instrument: str,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import run_desk_pattern_memory

    key = _validate_desk_instrument(instrument)
    return run_desk_pattern_memory(db, current_user.id, key, limit=limit)


@router.get("/scalping/desk/{instrument}/loss-autopsies")
def loss_autopsies_scalping_desk(
    instrument: str,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import run_desk_loss_autopsies

    key = _validate_desk_instrument(instrument)
    return run_desk_loss_autopsies(db, current_user.id, key, limit=limit)


@router.get("/scalping/desk/{instrument}/win-reinforcements")
def win_reinforcements_scalping_desk(
    instrument: str,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import run_desk_win_reinforcements

    key = _validate_desk_instrument(instrument)
    return run_desk_win_reinforcements(db, current_user.id, key, limit=limit)


@router.post("/scalping/desk/{instrument}/smc/backtest")
def smc_backtest_scalping_desk(
    instrument: str,
    payload: dict,
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import queue_smc_backtest_job

    key = _validate_desk_instrument(instrument)
    try:
        return queue_smc_backtest_job(current_user.id, key, payload)
    except Exception as exc:
        logger.exception("SMC backtest queue failed for user_id=%s instrument=%s", current_user.id, key)
        raise HTTPException(status_code=500, detail=f"SMC backtest failed: {exc}") from exc


@router.get("/scalping/desk/{instrument}/smc/backtest/{job_id}")
def smc_backtest_job_status(
    instrument: str,
    job_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import fetch_desk_backtest_job

    _validate_desk_instrument(instrument)
    return fetch_desk_backtest_job(current_user.id, job_id)


@router.post("/scalping/desk/{instrument}/smc/apply")
def apply_smc_scalping_strategy(
    instrument: str,
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.scalping_desk.service import apply_desk_smc_recommendation

    key = _validate_desk_instrument(instrument)
    return apply_desk_smc_recommendation(db, current_user.id, key, payload)


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


@router.get("/intraday/strategies")
def list_intraday_strategies(_: User = Depends(get_current_user)) -> dict:
    from trading_shared.strategies.equity_strategy_catalog import catalog_for_engine
    from trading_shared.strategies.strategy_code_validation import filter_catalog_for_engine

    return {"strategies": filter_catalog_for_engine("intraday", catalog_for_engine("intraday")), "desk": "intraday"}


@router.get("/intraday/desk")
def get_intraday_desk(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.intraday_desk.service import IntradayDeskService

    return IntradayDeskService(db, current_user.id).get_desk_payload()


@router.put("/intraday/desk/config")
def update_intraday_desk_config(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.intraday_desk.service import IntradayDeskService

    service = IntradayDeskService(db, current_user.id)
    return service.save_config({**service.get_config(), **payload})


@router.post("/intraday/desk/auto-trading")
def toggle_intraday_auto_trading(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.intraday_desk.service import IntradayDeskService

    return IntradayDeskService(db, current_user.id).toggle_auto_trading(bool(payload.get("enabled")))


@router.post("/intraday/desk/evaluate")
def evaluate_intraday_desk(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    import asyncio

    from trading_shared.strategies.intraday_desk.service import IntradayDeskService

    service = IntradayDeskService(db, current_user.id)
    try:
        return asyncio.run(service.run_auto_cycle())
    except AngelOneAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Intraday desk evaluate failed for user_id=%s", current_user.id)
        raise HTTPException(status_code=500, detail=f"Intraday auto cycle failed: {exc}") from exc


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


@router.get("/swing/strategies")
def list_swing_strategies(_: User = Depends(get_current_user)) -> dict:
    from trading_shared.strategies.equity_strategy_catalog import catalog_for_engine
    from trading_shared.strategies.strategy_code_validation import filter_catalog_for_engine

    return {"strategies": filter_catalog_for_engine("swing", catalog_for_engine("swing")), "desk": "swing"}


@router.get("/swing/desk")
def get_swing_desk(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.swing_desk.service import SwingDeskService

    return SwingDeskService(db, current_user.id).get_desk_payload()


@router.put("/swing/desk/config")
def update_swing_desk_config(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.swing_desk.service import SwingDeskService

    service = SwingDeskService(db, current_user.id)
    return service.save_config({**service.get_config(), **payload})


@router.post("/swing/desk/auto-trading")
def toggle_swing_auto_trading(
    payload: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    from trading_shared.strategies.swing_desk.service import SwingDeskService

    return SwingDeskService(db, current_user.id).toggle_auto_trading(bool(payload.get("enabled")))


@router.post("/swing/desk/evaluate")
def evaluate_swing_desk(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    import asyncio

    from trading_shared.strategies.swing_desk.service import SwingDeskService

    service = SwingDeskService(db, current_user.id)
    try:
        return asyncio.run(service.run_auto_cycle())
    except AngelOneAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Swing desk evaluate failed for user_id=%s", current_user.id)
        raise HTTPException(status_code=500, detail=f"Swing auto cycle failed: {exc}") from exc


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
