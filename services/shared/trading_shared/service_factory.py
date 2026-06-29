"""Factory for lightweight FastAPI microservice skeletons."""

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from trading_shared.config import get_settings
from trading_shared.db.session import get_db
from trading_shared.health import build_health


def create_service_app(name: str, description: str) -> FastAPI:
    settings = get_settings()
    docs_url = "/docs" if settings.ENABLE_OPENAPI_DOCS else None
    redoc_url = "/redoc" if settings.ENABLE_OPENAPI_DOCS else None
    app = FastAPI(
        title=name,
        description=description,
        version="0.1.0",
        docs_url=docs_url,
        redoc_url=redoc_url,
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

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "service": name, "env": settings.ENV}

    @app.get("/health/live")
    def health_live() -> dict:
        return {"status": "ok", "service": name}

    @app.get("/")
    def root() -> dict:
        return {"service": name, "env": settings.ENV}

    return app


def register_ready_health(app: FastAPI, service_name: str, *, redis_required: bool = False) -> None:
    @app.get("/health/ready")
    def health_ready(db: Session = Depends(get_db)) -> dict:
        payload = build_health(service_name, db=db, redis_required=redis_required)
        if payload["status"] != "ok":
            raise HTTPException(status_code=503, detail=payload)
        return payload
