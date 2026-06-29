"""Production startup validation and security helpers."""

from __future__ import annotations

WEAK_JWT_MARKERS = (
    "change_me",
    "super_secret",
    "replace_with",
    "dev_secret",
)

WEAK_ENCRYPTION_MARKERS = (
    "change_me",
    "phase1_dev",
    "replace_with",
)


def validate_production_settings(settings) -> None:
    if settings.ENV.lower() != "production":
        return

    errors: list[str] = []
    jwt = settings.JWT_SECRET or ""
    if len(jwt) < 32 or any(marker in jwt.lower() for marker in WEAK_JWT_MARKERS):
        errors.append("JWT_SECRET must be a strong random string (32+ chars) in production")

    enc = settings.ENCRYPTION_KEY or ""
    if len(enc) < 32 or any(marker in enc.lower() for marker in WEAK_ENCRYPTION_MARKERS):
        errors.append("ENCRYPTION_KEY must be a strong Fernet key in production")

    if "traderpass" in (settings.DATABASE_URL or ""):
        errors.append("DATABASE_URL must not use default traderpass in production")

    if errors:
        raise RuntimeError("Production configuration invalid: " + "; ".join(errors))
