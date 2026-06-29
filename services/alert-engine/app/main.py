import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from trading_shared.alerts.sender import AlertSender
from trading_shared.config import get_settings
from trading_shared.db.session import get_db, init_db
from trading_shared.health import build_health
from trading_shared.middleware.auth import get_current_user, require_roles
from trading_shared.models import User, UserRole
from trading_shared.service_factory import create_service_app

logger = logging.getLogger(__name__)
settings = get_settings()
app = create_service_app("alert-engine", "Production alerts via Telegram and email")
router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])
sender = AlertSender()


class AlertRequest(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    severity: str = "info"


@router.get("/status")
def status() -> dict:
    return {
        "status": "ok",
        "phase": 8,
        "channels_enabled": sender.enabled,
        "telegram": bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID),
        "email": bool(settings.SMTP_HOST and settings.ALERT_EMAIL_TO),
    }


@router.post("/send")
def send_alert(
    payload: AlertRequest,
    _: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
) -> dict:
    if not sender.enabled:
        raise HTTPException(status_code=503, detail="No alert channels configured")
    return sender.send(payload.subject, payload.body, payload.severity)


@router.post("/test")
def test_alert(_: User = Depends(require_roles(UserRole.ADMIN))) -> dict:
    if not sender.enabled:
        raise HTTPException(status_code=503, detail="Configure TELEGRAM_* or SMTP_* in .env")
    return sender.send("Trading Bot Test Alert", "Alert engine is configured and reachable.", "info")


app.include_router(router)


@app.get("/health/ready")
def ready(db: Session = Depends(get_db)) -> dict:
    payload = build_health("alert-engine", db=db, redis_required=True)
    if payload["status"] != "ok":
        raise HTTPException(status_code=503, detail=payload)
    return payload


def wait_for_db(retries: int = 20, delay_seconds: int = 2) -> None:
    for attempt in range(1, retries + 1):
        try:
            init_db()
            return
        except Exception:
            if attempt == retries:
                raise
            time.sleep(delay_seconds)


@app.on_event("startup")
def on_startup() -> None:
    wait_for_db()
