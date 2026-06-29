import logging

from fastapi import APIRouter, Depends

from trading_shared.config import get_settings
from trading_shared.middleware.auth import get_current_user, require_roles
from trading_shared.models import User, UserRole
from trading_shared.risk.manager import RiskManager
from trading_shared.schemas.risk import (
    EquityUpdate,
    RegisterTradeRequest,
    RiskLimitsUpdate,
    TradeEvaluationRequest,
)
from trading_shared.service_factory import create_service_app

logger = logging.getLogger(__name__)
settings = get_settings()
app = create_service_app("risk-manager", "Production risk controls and position sizing")
router = APIRouter(prefix="/api/v1/risk", tags=["risk"])


def get_risk_manager() -> RiskManager:
    return RiskManager(settings.REDIS_URL)


@router.get("/status")
def risk_status(
    _: User = Depends(get_current_user),
    manager: RiskManager = Depends(get_risk_manager),
) -> dict:
    return manager.status()


@router.get("/limits")
def get_limits(
    _: User = Depends(get_current_user),
    manager: RiskManager = Depends(get_risk_manager),
) -> dict:
    meter = manager.status()
    return {"limits": meter["limits"], "state": meter["state"]}


@router.patch("/limits")
def update_limits(
    payload: RiskLimitsUpdate,
    _: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
    manager: RiskManager = Depends(get_risk_manager),
) -> dict:
    return manager.update_limits(**payload.model_dump(exclude_none=True))


@router.post("/equity")
def set_equity(
    payload: EquityUpdate,
    _: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
    manager: RiskManager = Depends(get_risk_manager),
) -> dict:
    return manager.set_equity(payload.equity)


@router.post("/evaluate")
def evaluate_trade(
    payload: TradeEvaluationRequest,
    _: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
    manager: RiskManager = Depends(get_risk_manager),
) -> dict:
    return manager.evaluate_trade(payload.entry, payload.stoploss, payload.side)


@router.post("/register")
def register_trade(
    payload: RegisterTradeRequest,
    _: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
    manager: RiskManager = Depends(get_risk_manager),
) -> dict:
    return manager.register_trade(payload.realized_pnl, payload.notional)


@router.post("/reset-halt")
def reset_halt(
    _: User = Depends(require_roles(UserRole.ADMIN)),
    manager: RiskManager = Depends(get_risk_manager),
) -> dict:
    return manager.reset_halt()


@router.get("/can-trade")
def can_trade(
    _: User = Depends(get_current_user),
    manager: RiskManager = Depends(get_risk_manager),
) -> dict:
    can, reason = manager.engine.can_trade()
    return {"can_trade": can, "reason": reason}


app.include_router(router)


@app.on_event("startup")
def on_startup() -> None:
    manager = RiskManager(settings.REDIS_URL)
    if not manager.redis.get("risk:state"):
        manager.save()
        logger.info("Initialized default risk state in Redis")
