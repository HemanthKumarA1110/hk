import logging
import time

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response

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


@router.get("/results")
def list_results(
    run_from: date | None = Query(default=None, description="Filter runs created on/after this date"),
    run_to: date | None = Query(default=None, description="Filter runs created on/before this date"),
    engine: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    db=Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    orchestrator = BacktestOrchestrator(db)
    runs = orchestrator.list_runs_filtered(
        user.id,
        run_from=run_from,
        run_to=run_to,
        engine=engine,
        status=status,
        limit=limit,
    )
    rows = [orchestrator.serialize_run_summary(r) for r in runs]
    return {
        "results": rows,
        "count": len(rows),
        "filters": {
            "run_from": run_from.isoformat() if run_from else None,
            "run_to": run_to.isoformat() if run_to else None,
            "engine": engine,
            "status": status,
        },
    }


@router.get("/results/export")
def export_results(
    run_from: date | None = Query(default=None),
    run_to: date | None = Query(default=None),
    engine: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=2000, ge=1, le=5000),
    db=Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    orchestrator = BacktestOrchestrator(db)
    runs = orchestrator.list_runs_filtered(
        user.id,
        run_from=run_from,
        run_to=run_to,
        engine=engine,
        status=status,
        limit=limit,
    )
    rows = [orchestrator.serialize_run_summary(r) for r in runs]
    headers = [
        "Run ID",
        "Run Date",
        "Engine",
        "Strategy",
        "Symbol",
        "Period From",
        "Period To",
        "Interval",
        "Trades",
        "Win Rate %",
        "Total P&L",
        "Max Drawdown",
        "Profit Factor",
        "AI Entry",
        "AI Exit",
        "Status",
        "Data Source",
    ]

    def cell(value) -> str:
        text = "" if value is None else str(value)
        return '"' + text.replace('"', '""') + '"'

    lines = [",".join(headers)]
    for row in rows:
        lines.append(
            ",".join(
                [
                    cell(row.get("run_id")),
                    cell(row.get("created_at")),
                    cell(row.get("engine")),
                    cell(row.get("strategy_code")),
                    cell(row.get("symbol")),
                    cell(row.get("from_date")),
                    cell(row.get("to_date")),
                    cell(row.get("interval")),
                    cell(row.get("total_trades")),
                    cell(row.get("win_rate")),
                    cell(row.get("total_pnl")),
                    cell(row.get("max_drawdown")),
                    cell(row.get("profit_factor")),
                    cell(row.get("ai_entry")),
                    cell(row.get("ai_exit")),
                    cell(row.get("status")),
                    cell(row.get("data_source")),
                ]
            )
        )
    body = "\ufeff" + "\n".join(lines)
    filename = f"backtest-results-{date.today().isoformat()}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/results")
def clear_results(
    run_from: date | None = Query(default=None),
    run_to: date | None = Query(default=None),
    engine: str | None = Query(default=None),
    status: str | None = Query(default=None),
    all: bool = Query(default=False, alias="delete_all", description="Delete entire backtest archive"),
    db=Depends(get_db),
    user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
) -> dict:
    orchestrator = BacktestOrchestrator(db)
    deleted = orchestrator.delete_runs_filtered(
        user.id,
        run_from=run_from,
        run_to=run_to,
        engine=engine,
        status=status,
        delete_all=all,
    )
    return {"deleted": deleted, "message": f"Removed {deleted} backtest run(s)"}


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
