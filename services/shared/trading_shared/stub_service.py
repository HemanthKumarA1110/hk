"""Minimal stub service factory for Phase 6+ services."""

from fastapi import APIRouter

from trading_shared.service_factory import create_service_app


def create_stub_service(name: str, description: str, prefix: str, phase: int = 6) -> tuple:
    app = create_service_app(name, description)
    router = APIRouter(prefix=prefix, tags=[name.split("-")[0]])

    @router.get("/status")
    def status() -> dict:
        return {"status": "stub", "service": name, "phase": phase}

    app.include_router(router)
    return app
