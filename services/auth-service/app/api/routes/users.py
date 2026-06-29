from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from trading_shared.db.session import get_db
from trading_shared.middleware.auth import get_current_user, require_roles
from trading_shared.models import User, UserRole
from trading_shared.schemas.auth import UserResponse

router = APIRouter()


@router.get("/", response_model=List[UserResponse])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> list[User]:
    return db.query(User).order_by(User.id.asc()).all()


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.role != UserRole.ADMIN and current_user.id != user_id:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user
