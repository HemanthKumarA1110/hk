from pydantic import BaseModel, Field


class BrokerCredentialRequest(BaseModel):
    api_key: str = Field(..., min_length=8)
    client_code: str = Field(..., min_length=1, max_length=32)
    password: str = Field(..., min_length=1)
    totp_secret: str = Field(..., min_length=16, description="Base32 TOTP secret from Angel One QR")


class BrokerConnectionResponse(BaseModel):
    connected: bool = False
    credentials_configured: bool = False
    session_valid: bool = False
    needs_reconnect: bool = False
    client_code: str | None = None
    feed_token_available: bool = False
    expires_at: str | None = None
    cached_in_redis: bool = False
    error: str | None = None


class BrokerProfileResponse(BaseModel):
    status: bool
    data: dict | None = None
    message: str | None = None


class BrokerFundsResponse(BaseModel):
    status: bool
    data: dict | None = None
    message: str | None = None


class BrokerHoldingsResponse(BaseModel):
    status: bool
    data: list | dict | None = None


class BrokerPositionsResponse(BaseModel):
    status: bool
    data: list | dict | None = None


class BrokerAccountSnapshotResponse(BaseModel):
    connected: bool = False
    message: str | None = None
    orders: list[dict] = []
    positions: list[dict] = []
    holdings: list[dict] = []
    trades: list[dict] = []
    fetched_at: str | None = None
