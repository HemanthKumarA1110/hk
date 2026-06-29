from fastapi import APIRouter

from trading_shared.service_factory import create_service_app

app = create_service_app("analytics-engine", "Performance analytics (Phase 6)")
router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])


@router.get("/performance")
def performance() -> dict:
    return {"sharpe": 0, "max_drawdown": 0, "win_rate": 0, "status": "stub"}


app.include_router(router)
