from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from trading_shared.config import get_settings
from trading_shared.models import AuditLog, User, UserRole
from trading_shared.schemas.auth import UserRegisterRequest, UserRoleEnum
from trading_shared.security.jwt_handler import create_access_token, create_refresh_token, decode_token
from trading_shared.security.password import hash_password, verify_password


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    def register(self, payload: UserRegisterRequest) -> User:
        if self.settings.ENV.lower() == "production" and not self.settings.ALLOW_PUBLIC_REGISTRATION:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Public registration is disabled in production",
            )

        if self.db.query(User).filter(User.username == payload.username).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
        if self.db.query(User).filter(User.email == payload.email).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

        role = payload.role
        if self.settings.ENV.lower() == "production":
            role = UserRoleEnum.VIEWER

        user = User(
            username=payload.username,
            email=payload.email,
            hashed_password=hash_password(payload.password),
            role=UserRole(role.value),
            is_active=True,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        self._audit(user.id, "register", "user", f"Registered user {user.username}")
        return user

    def login(self, username: str, password: str) -> dict:
        user = self.db.query(User).filter(User.username == username, User.is_active.is_(True)).first()
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        claims = {"role": user.role.value, "username": user.username}
        access_token = create_access_token(str(user.id), claims)
        refresh_token = create_refresh_token(str(user.id))
        self._audit(user.id, "login", "user", "Successful login")
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": self.settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    def refresh(self, refresh_token: str) -> dict:
        try:
            payload = decode_token(refresh_token)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

        if payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

        user = self.db.query(User).filter(User.id == int(payload["sub"]), User.is_active.is_(True)).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

        claims = {"role": user.role.value, "username": user.username}
        access_token = create_access_token(str(user.id), claims)
        new_refresh = create_refresh_token(str(user.id))
        return {
            "access_token": access_token,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "expires_in": self.settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    def _audit(self, user_id: int | None, action: str, resource: str, details: str) -> None:
        self.db.add(
            AuditLog(
                user_id=user_id,
                action=action,
                resource=resource,
                details=details,
                created_at=datetime.now(timezone.utc),
            )
        )
        self.db.commit()
