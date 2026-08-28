from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from trading_shared.config import get_settings
from trading_shared.models import AuditLog, User, UserRole
from trading_shared.schemas.auth import (
    AdminCreateUserRequest,
    AdminResetPasswordRequest,
    AdminUpdateUserRequest,
    ChangePasswordRequest,
    UserRegisterRequest,
    UserRoleEnum,
)
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

        self._ensure_unique_username_email(payload.username, payload.email)

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
        self.record_audit(user.id, "register", "user", f"Registered user {user.username}")
        return user

    def create_user_as_admin(self, payload: AdminCreateUserRequest, actor: User) -> User:
        self._ensure_unique_username_email(payload.username, payload.email)

        user = User(
            username=payload.username,
            email=payload.email,
            hashed_password=hash_password(payload.password),
            role=UserRole(payload.role.value),
            is_active=payload.is_active,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        self.record_audit(
            actor.id,
            "admin_create_user",
            "user",
            f"Created user {user.username} role={user.role.value}",
        )
        return user

    def update_user(self, user_id: int, payload: AdminUpdateUserRequest, actor: User) -> User:
        user = self._get_user_or_404(user_id)

        if payload.email is not None and payload.email != user.email:
            if self.db.query(User).filter(User.email == payload.email, User.id != user_id).first():
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
            user.email = payload.email

        if payload.role is not None:
            if user.id == actor.id and payload.role != UserRoleEnum.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot demote your own admin role",
                )
            user.role = UserRole(payload.role.value)

        if payload.is_active is not None:
            if user.id == actor.id and not payload.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot deactivate your own account",
                )
            user.is_active = payload.is_active

        self.db.commit()
        self.db.refresh(user)
        self.record_audit(
            actor.id,
            "admin_update_user",
            "user",
            f"Updated user {user.username} role={user.role.value} active={user.is_active}",
        )
        return user

    def change_password(self, user: User, payload: ChangePasswordRequest) -> dict:
        if not verify_password(payload.current_password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
        if payload.current_password == payload.new_password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="New password must differ from current password",
            )

        user.hashed_password = hash_password(payload.new_password)
        self.db.commit()
        self.record_audit(user.id, "change_password", "user", "Password changed by user")
        return {"status": "ok", "message": "Password updated"}

    def admin_reset_password(
        self, user_id: int, payload: AdminResetPasswordRequest, actor: User
    ) -> dict:
        user = self._get_user_or_404(user_id)
        user.hashed_password = hash_password(payload.new_password)
        self.db.commit()
        self.record_audit(
            actor.id,
            "admin_reset_password",
            "user",
            f"Password reset for user {user.username}",
        )
        return {"status": "ok", "message": f"Password reset for {user.username}"}

    def login(self, username: str, password: str) -> dict:
        user = self.db.query(User).filter(User.username == username).first()
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is deactivated. Contact an administrator.",
            )

        claims = {"role": user.role.value, "username": user.username}
        access_token = create_access_token(str(user.id), claims)
        refresh_token = create_refresh_token(str(user.id))
        self.record_audit(user.id, "login", "user", "Successful login")
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

        user = self.db.query(User).filter(User.id == int(payload["sub"])).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is deactivated. Contact an administrator.",
            )

        claims = {"role": user.role.value, "username": user.username}
        access_token = create_access_token(str(user.id), claims)
        new_refresh = create_refresh_token(str(user.id))
        return {
            "access_token": access_token,
            "refresh_token": new_refresh,
            "token_type": "bearer",
            "expires_in": self.settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        }

    def _get_user_or_404(self, user_id: int) -> User:
        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return user

    def _ensure_unique_username_email(self, username: str, email: str) -> None:
        if self.db.query(User).filter(User.username == username).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
        if self.db.query(User).filter(User.email == email).first():
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    def record_audit(self, user_id: int | None, action: str, resource: str, details: str) -> None:
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
