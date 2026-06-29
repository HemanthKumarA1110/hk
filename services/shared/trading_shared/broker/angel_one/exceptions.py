class AngelOneError(Exception):
    """Base Angel One integration error."""


class AngelOneAuthError(AngelOneError):
    """Authentication or session error."""


class AngelOneAPIError(AngelOneError):
    """API request failed."""

    def __init__(self, message: str, status_code: int | None = None, payload: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}
