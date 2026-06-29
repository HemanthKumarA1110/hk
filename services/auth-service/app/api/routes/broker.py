from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.services.broker_service import BrokerAuthService
from trading_shared.broker.angel_one.exceptions import AngelOneAPIError, AngelOneAuthError
from trading_shared.db.session import get_db
from trading_shared.middleware.auth import get_current_user, require_roles
from trading_shared.models import User, UserRole
from trading_shared.schemas.broker import (
    BrokerAccountSnapshotResponse,
    BrokerConnectionResponse,
    BrokerCredentialRequest,
    BrokerFundsResponse,
    BrokerHoldingsResponse,
    BrokerPositionsResponse,
    BrokerProfileResponse,
)

router = APIRouter()


@router.post("/credentials")
def save_credentials(
    payload: BrokerCredentialRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    service = BrokerAuthService(db)
    return service.save_credentials(current_user, payload)


@router.post("/connect", response_model=BrokerConnectionResponse)
async def connect_broker(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    service = BrokerAuthService(db)
    result = await service.connect(current_user)
    status = service.status(current_user)
    return {**status, **result}


@router.post("/disconnect")
async def disconnect_broker(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    service = BrokerAuthService(db)
    return await service.disconnect(current_user)


@router.get("/status", response_model=BrokerConnectionResponse)
def broker_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    service = BrokerAuthService(db)
    return service.status(current_user)


@router.get("/profile", response_model=BrokerProfileResponse)
async def broker_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    service = BrokerAuthService(db)
    return await service.profile(current_user)


@router.get("/funds", response_model=BrokerFundsResponse)
async def broker_funds(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    service = BrokerAuthService(db)
    return await service.funds(current_user)


@router.get("/holdings", response_model=BrokerHoldingsResponse)
async def broker_holdings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    service = BrokerAuthService(db)
    return await service.holdings(current_user)


@router.get("/positions", response_model=BrokerPositionsResponse)
async def broker_positions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    service = BrokerAuthService(db)
    return await service.positions(current_user)


@router.get("/account", response_model=BrokerAccountSnapshotResponse)
async def broker_account_snapshot(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    service = BrokerAuthService(db)
    return await service.account_snapshot(current_user)


@router.delete("/orders/{order_id}")
async def cancel_broker_order(
    order_id: str,
    variety: str = "NORMAL",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
) -> dict:
    service = BrokerAuthService(db)
    try:
        return await service.cancel_order(current_user, order_id, variety)
    except AngelOneAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except AngelOneAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Cancel failed: {exc}") from exc


@router.post("/system/connect")
async def system_connect(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> dict:
    service = BrokerAuthService(db)
    return await service.connect_with_env_credentials()
