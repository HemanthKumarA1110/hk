import logging
import time

from fastapi import APIRouter, Depends, HTTPException

from trading_shared.broker.angel_one.exceptions import AngelOneAuthError
from trading_shared.db.session import get_db, init_db
from trading_shared.middleware.auth import get_current_user
from trading_shared.models import User
from trading_shared.portfolio.sync import PortfolioSync
from trading_shared.service_factory import create_service_app

logger = logging.getLogger(__name__)
app = create_service_app("portfolio-manager", "Live portfolio sync from Angel One")
router = APIRouter(prefix="/api/v1/portfolio", tags=["portfolio"])


@router.get("/summary")
async def summary(
    db=Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return await PortfolioSync(db, user.id).summary()
    except AngelOneAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@router.get("/positions")
async def positions(
    db=Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    try:
        return await PortfolioSync(db, user.id).positions()
    except AngelOneAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


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
