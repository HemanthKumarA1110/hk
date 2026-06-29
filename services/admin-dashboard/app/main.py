import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from trading_shared.admin.overview import AdminOverviewAggregator
from trading_shared.db.session import get_db, init_db
from trading_shared.middleware.auth import get_current_user
from trading_shared.models import User
from trading_shared.service_factory import create_service_app

app = create_service_app("admin-dashboard", "Institutional dashboard BFF and overview aggregation")
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/overview")
def overview(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return AdminOverviewAggregator(db).overview()


@router.get("/equity-curve")
def equity_curve(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return AdminOverviewAggregator(db).equity_curve()


@router.get("/journal")
def journal(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return AdminOverviewAggregator(db).journal_entries()


@router.get("/backtest/preview")
def backtest_preview(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return AdminOverviewAggregator(db).backtest_preview()


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
