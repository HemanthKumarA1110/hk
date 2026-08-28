from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.services.auth_service import AuthService
from trading_shared.db.session import get_db
from trading_shared.middleware.auth import get_current_user
from trading_shared.models import User
from trading_shared.schemas.auth import (
    ChangePasswordRequest,
    RefreshTokenRequest,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)

router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=201)
def register(payload: UserRegisterRequest, db: Session = Depends(get_db)) -> User:
    service = AuthService(db)
    return service.register(payload)


@router.post("/login", response_model=TokenResponse)
def login(payload: UserLoginRequest, db: Session = Depends(get_db)) -> dict:
    service = AuthService(db)
    return service.login(payload.username, payload.password)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshTokenRequest, db: Session = Depends(get_db)) -> dict:
    service = AuthService(db)
    return service.refresh(payload.refresh_token)


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/change-password")
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    service = AuthService(db)
    return service.change_password(current_user, payload)
