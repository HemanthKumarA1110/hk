from pydantic import BaseModel, Field, field_validator, model_validator


class BrokerCredentialRequest(BaseModel):
    """Create or partially update Angel One credentials.

    Blank / omitted fields keep the previously stored secret when credentials
    already exist. First-time setup still requires all four fields (enforced
    in the session manager).
    """

    api_key: str | None = Field(default=None, min_length=8)
    client_code: str | None = Field(default=None, min_length=1, max_length=32)
    password: str | None = Field(default=None, min_length=1)
    totp_secret: str | None = Field(
        default=None,
        min_length=16,
        description="Base32 TOTP secret from Angel One QR",
    )

    @field_validator("api_key", "client_code", "password", "totp_secret", mode="before")
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "BrokerCredentialRequest":
        if not any([self.api_key, self.client_code, self.password, self.totp_secret]):
            raise ValueError("Provide at least one credential field to save or update")
        return self


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
