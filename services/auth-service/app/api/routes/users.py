from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.services.auth_service import AuthService
from app.services.broker_service import BrokerAuthService
from trading_shared.db.session import get_db
from trading_shared.middleware.auth import get_current_user, require_roles
from trading_shared.models import User, UserRole
from trading_shared.schemas.auth import (
    AdminCreateUserRequest,
    AdminResetPasswordRequest,
    AdminUpdateUserRequest,
    UserResponse,
)
from trading_shared.schemas.broker import BrokerConnectionResponse, BrokerCredentialRequest

router = APIRouter()


@router.get("/", response_model=List[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> list[User]:
    return db.query(User).order_by(User.id.asc()).all()


@router.post("/", response_model=UserResponse, status_code=201)
def create_user(
    payload: AdminCreateUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> User:
    service = AuthService(db)
    return service.create_user_as_admin(payload, current_user)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role != UserRole.ADMIN and current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    payload: AdminUpdateUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> User:
    service = AuthService(db)
    return service.update_user(user_id, payload, current_user)


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: int,
    payload: AdminResetPasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> dict:
    service = AuthService(db)
    return service.admin_reset_password(user_id, payload, current_user)


@router.get("/{user_id}/broker/status", response_model=BrokerConnectionResponse)
def admin_broker_status(
    user_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> dict:
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    service = BrokerAuthService(db)
    return service.status(target)


@router.post("/{user_id}/broker/credentials")
def admin_save_broker_credentials(
    user_id: int,
    payload: BrokerCredentialRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> dict:
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    service = BrokerAuthService(db)
    result = service.save_credentials(target, payload)
    AuthService(db).record_audit(
        current_user.id,
        "admin_save_broker_credentials",
        "broker",
        f"Saved Angel One credentials for user {target.username}",
    )
    return result


@router.post("/{user_id}/broker/connect", response_model=BrokerConnectionResponse)
async def admin_connect_broker(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> dict:
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    service = BrokerAuthService(db)
    result = await service.connect(target)
    status_payload = service.status(target)
    AuthService(db).record_audit(
        current_user.id,
        "admin_connect_broker",
        "broker",
        f"Connected Angel One for user {target.username}",
    )
    return {**status_payload, **result}
