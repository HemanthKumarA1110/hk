from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRoleEnum(str, Enum):
    ADMIN = "admin"
    TRADER = "trader"
    VIEWER = "viewer"


class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    role: UserRoleEnum = UserRoleEnum.TRADER


class UserLoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: UserRoleEnum
    is_active: bool
