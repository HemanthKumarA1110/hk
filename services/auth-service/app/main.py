import logging
import time

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.api.routes import auth, broker, users
from trading_shared.config import get_settings
from trading_shared.db.session import SessionLocal, get_db, init_db
from trading_shared.health import build_health, check_redis
from trading_shared.models import User, UserRole
from trading_shared.security.password import hash_password

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title="Auth Service",
    description="JWT authentication, RBAC, and Angel One broker session management",
    version="0.1.0",
    docs_url="/docs" if settings.ENABLE_OPENAPI_DOCS else None,
    redoc_url="/redoc" if settings.ENABLE_OPENAPI_DOCS else None,
    openapi_url="/openapi.json" if settings.ENABLE_OPENAPI_DOCS else None,
)

origins = [origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
app.include_router(broker.router, prefix="/api/v1/broker", tags=["broker"])


def wait_for_db(retries: int = 20, delay_seconds: int = 2) -> None:
    for attempt in range(1, retries + 1):
        try:
            init_db()
            return
        except OperationalError:
            if attempt == retries:
                raise
            time.sleep(delay_seconds)


def seed_admin_user() -> None:
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if admin:
            return
        db.add(
            User(
                username="admin",
                email="admin@trading.local",
                hashed_password=hash_password("Admin@12345"),
                role=UserRole.ADMIN,
                is_active=True,
            )
        )
        db.commit()
        logger.info("Seeded default admin user: admin / Admin@12345")
    finally:
        db.close()


@app.on_event("startup")
def on_startup() -> None:
    wait_for_db()
    seed_admin_user()


@app.get("/health")
def health() -> dict:
    redis_status = check_redis()
    status = "ok" if redis_status["status"] == "ok" else "degraded"
    return {
        "status": status,
        "service": "auth-service",
        "env": settings.ENV,
        "redis": redis_status,
    }


@app.get("/health/live")
def health_live() -> dict:
    return {"status": "ok", "service": "auth-service"}


@app.get("/health/ready")
def health_ready(db: Session = Depends(get_db)) -> dict:
    payload = build_health("auth-service", db=db, redis_required=True)
    if payload["status"] != "ok":
        raise HTTPException(status_code=503, detail=payload)
    return payload


@app.get("/")
def root() -> dict:
    return {"service": "auth-service", "docs": "/docs"}
