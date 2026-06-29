import logging
import time

from fastapi import APIRouter, Depends, HTTPException

from trading_shared.backtest.orchestrator import BacktestOrchestrator
from trading_shared.db.session import get_db, init_db
from trading_shared.middleware.auth import get_current_user, require_roles
from trading_shared.models import User, UserRole
from trading_shared.schemas.backtest import BacktestRunCreated, BacktestRunRequest, BacktestRunResponse
from trading_shared.service_factory import create_service_app

logger = logging.getLogger(__name__)
app = create_service_app("backtesting-engine", "Strategy backtesting with production engines")
router = APIRouter(prefix="/api/v1/backtest", tags=["backtest"])


@router.get("/status")
def status() -> dict:
    return {"status": "ok", "phase": 6, "engines": ["scalping", "intraday", "swing"]}


@router.post("/run", response_model=BacktestRunCreated)
def run_backtest(
    payload: BacktestRunRequest,
    db=Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
) -> dict:
    if payload.engine not in ("scalping", "intraday", "swing"):
        raise HTTPException(status_code=400, detail="engine must be scalping, intraday, or swing")

    orchestrator = BacktestOrchestrator(db)
    run = orchestrator.create_run(user.id, payload)

    try:
        from app.tasks import enqueue_backtest

        enqueue_backtest(run.id)
        message = "Backtest queued for async execution"
    except Exception:
        logger.info("Celery unavailable, running backtest synchronously for run %s", run.id)
        orchestrator.execute_run(run.id)
        run = orchestrator.get_run(run.id, user.id)
        message = "Backtest completed synchronously"

    return {"run_id": run.id, "status": run.status, "message": message}


@router.get("/runs", response_model=list[BacktestRunResponse])
def list_runs(
    db=Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    runs = BacktestOrchestrator(db).list_runs(user.id)
    return [BacktestOrchestrator.serialize_run(r) for r in runs]


@router.get("/runs/{run_id}", response_model=BacktestRunResponse)
def get_run(
    run_id: int,
    db=Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    run = BacktestOrchestrator(db).get_run(run_id, user.id)
    if not run:
        raise HTTPException(status_code=404, detail="Backtest run not found")
    return BacktestOrchestrator.serialize_run(run)


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


@app.on_event("startup")
def on_startup() -> None:
    wait_for_db()
