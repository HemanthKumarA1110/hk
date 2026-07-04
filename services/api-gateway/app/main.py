import logging
import time

import httpx
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from trading_shared.config import get_settings
from trading_shared.health import check_redis
from trading_shared.middleware.http import RequestLoggingMiddleware, SecurityHeadersMiddleware
from trading_shared.middleware.rate_limit import RateLimiter

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title="Trading Bot API Gateway",
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
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)

limiter = RateLimiter()

SERVICE_MAP = {
    "/api/v1/auth": settings.AUTH_SERVICE_URL,
    "/api/v1/users": settings.AUTH_SERVICE_URL,
    "/api/v1/broker": settings.AUTH_SERVICE_URL,
    "/api/v1/market": settings.MARKET_DATA_SERVICE_URL,
    "/api/v1/strategies": settings.STRATEGY_ENGINE_URL,
    "/api/v1/ai": settings.AI_DECISION_ENGINE_URL,
    "/api/v1/risk": settings.RISK_MANAGER_URL,
    "/api/v1/orders": settings.ORDER_EXECUTION_URL,
    "/api/v1/backtest": settings.BACKTESTING_ENGINE_URL,
    "/api/v1/portfolio": settings.PORTFOLIO_MANAGER_URL,
    "/api/v1/alerts": settings.ALERT_ENGINE_URL,
    "/api/v1/analytics": settings.ANALYTICS_ENGINE_URL,
    "/api/v1/journal": settings.TRADE_JOURNAL_URL,
    "/api/v1/admin": settings.ADMIN_DASHBOARD_URL,
}

CRITICAL_SERVICES = (
    ("auth-service", settings.AUTH_SERVICE_URL),
    ("market-data-service", settings.MARKET_DATA_SERVICE_URL),
    ("order-execution-engine", settings.ORDER_EXECUTION_URL),
    ("risk-manager", settings.RISK_MANAGER_URL),
)


def resolve_upstream(path: str) -> str | None:
    for prefix, upstream in SERVICE_MAP.items():
        if path.startswith(prefix):
            return upstream
    return None


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(request: Request, path: str) -> None:
    ip = _client_ip(request)
    if path.startswith("/api/v1/auth/login") or path.startswith("/api/v1/auth/register"):
        if not limiter.allow(f"login:{ip}", settings.RATE_LIMIT_LOGIN_PER_MINUTE):
            raise HTTPException(status_code=429, detail="Too many authentication attempts")
    if path.startswith("/api/v1/orders") and request.method in ("POST", "PATCH", "DELETE"):
        if not limiter.allow(f"orders:{ip}", settings.RATE_LIMIT_ORDERS_PER_MINUTE):
            raise HTTPException(status_code=429, detail="Too many order requests")


@app.get("/health")
async def health() -> dict:
    redis_status = check_redis()
    status = "ok" if redis_status["status"] == "ok" else "degraded"
    return {"status": status, "service": "api-gateway", "env": settings.ENV, "redis": redis_status}


@app.get("/health/aggregate")
async def aggregate_health() -> dict:
    if not settings.EXPOSE_SERVICE_REGISTRY and settings.ENV.lower() == "production":
        raise HTTPException(status_code=404, detail="Not found")

    results = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for name, url in CRITICAL_SERVICES:
            try:
                response = await client.get(f"{url}/health")
                results[name] = {"status": response.status_code, "body": response.json()}
            except Exception as exc:
                results[name] = {"status": "error", "detail": str(exc)}

    overall = "ok" if all(r.get("status") == 200 for r in results.values()) else "degraded"
    return {"status": overall, "services": results, "checked_at": time.time()}


@app.get("/api/v1/services")
async def service_registry() -> dict:
    if not settings.EXPOSE_SERVICE_REGISTRY:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "gateway": "api-gateway:8000",
        "services": {
            "auth-service": settings.AUTH_SERVICE_URL,
            "market-data-service": settings.MARKET_DATA_SERVICE_URL,
            "strategy-engine": settings.STRATEGY_ENGINE_URL,
            "ai-decision-engine": settings.AI_DECISION_ENGINE_URL,
            "risk-manager": settings.RISK_MANAGER_URL,
            "order-execution-engine": settings.ORDER_EXECUTION_URL,
            "backtesting-engine": settings.BACKTESTING_ENGINE_URL,
            "portfolio-manager": settings.PORTFOLIO_MANAGER_URL,
            "alert-engine": settings.ALERT_ENGINE_URL,
            "analytics-engine": settings.ANALYTICS_ENGINE_URL,
            "trade-journal-engine": settings.TRADE_JOURNAL_URL,
            "admin-dashboard": settings.ADMIN_DASHBOARD_URL,
        },
    }


def _proxy_timeout(path: str) -> httpx.Timeout:
    """Upstream read timeouts — long jobs must not hit gateway ReadTimeout."""
    if path.startswith("/api/v1/strategies/"):
        return httpx.Timeout(connect=30.0, read=1800.0, write=1800.0, pool=30.0)
    if "/backtest" in path or "/smc/" in path:
        return httpx.Timeout(connect=30.0, read=1800.0, write=1800.0, pool=30.0)
    return httpx.Timeout(connect=15.0, read=120.0, write=120.0, pool=15.0)


@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def proxy(full_path: str, request: Request) -> Response:
    path = f"/{full_path}"
    _enforce_rate_limit(request, path)
    upstream = resolve_upstream(path)
    if not upstream:
        return Response(content='{"detail":"Route not mapped"}', status_code=404, media_type="application/json")

    target_url = f"{upstream}{path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    headers = {key: value for key, value in request.headers.items() if key.lower() != "host"}
    body = await request.body()

    timeout = _proxy_timeout(path)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            upstream_response = await client.request(
                request.method,
                target_url,
                headers=headers,
                content=body,
            )
    except httpx.ReadTimeout:
        logger.error("Gateway read timeout proxying %s %s", request.method, path)
        return Response(
            content='{"detail":"Upstream request timed out. Long backtests run as background jobs — poll job status."}',
            status_code=504,
            media_type="application/json",
        )
    except httpx.RequestError as exc:
        logger.error("Gateway upstream error for %s %s: %s", request.method, path, exc)
        return Response(
            content=f'{{"detail":"Upstream unavailable: {exc}"}}',
            status_code=502,
            media_type="application/json",
        )

    excluded_headers = {"content-encoding", "content-length", "transfer-encoding", "connection"}
    response_headers = {
        key: value for key, value in upstream_response.headers.items() if key.lower() not in excluded_headers
    }
    return Response(
        content=upstream_response.content,
        status_code=upstream_response.status_code,
        headers=response_headers,
        media_type=upstream_response.headers.get("content-type"),
    )
