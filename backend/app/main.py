import time

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.exc import OperationalError
from sqlmodel import select
from app.api import routes, risk_endpoints
from app.api.paper_trading import router as paper_router
from app.api.journal import router as journal_router
from app.api.broker import router as broker_router
from app.api.dashboard import router as dashboard_router
from app.core.config import settings
from app.db.session import Session, engine, init_db
from app.models import Portfolio, Strategy

REQUEST_COUNTER = Counter(
    'app_http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'http_status'],
)
REQUEST_LATENCY = Histogram(
    'app_http_request_duration_seconds',
    'HTTP request latency in seconds',
    ['method', 'endpoint'],
)

app = FastAPI(title="Indian Algo Trading Bot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(routes.router, prefix="/api")
app.include_router(risk_endpoints.router, prefix="/api")
app.include_router(paper_router, prefix="/api")
app.include_router(journal_router, prefix="/api")
app.include_router(broker_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")

@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    request_latency = time.time() - start_time
    endpoint = request.url.path
    REQUEST_LATENCY.labels(request.method, endpoint).observe(request_latency)
    REQUEST_COUNTER.labels(request.method, endpoint, response.status_code).inc()
    return response


def wait_for_db(retries: int = 10, delay_seconds: int = 2):
    for attempt in range(1, retries + 1):
        try:
            init_db()
            return
        except OperationalError:
            if attempt == retries:
                raise
            time.sleep(delay_seconds)

def seed_initial_data():
    with Session(engine) as session:
        portfolio_exists = session.exec(select(Portfolio)).first()
        if not portfolio_exists:
            session.add(
                Portfolio(
                    user_id=1,
                    capital=100000.0,
                    available_margin=100000.0,
                    daily_pnl=0.0,
                    weekly_pnl=0.0,
                    monthly_pnl=0.0,
                    roi=0.0,
                )
            )

        strategy_exists = session.exec(select(Strategy)).first()
        if not strategy_exists:
            session.add_all(
                [
                    Strategy(name='scalping', enabled=True, params='{}'),
                    Strategy(name='intraday', enabled=True, params='{}'),
                    Strategy(name='swing', enabled=True, params='{}'),
                ]
            )
        session.commit()

@app.on_event('startup')
def on_startup():
    wait_for_db()
    try:
        seed_initial_data()
    except OperationalError:
        pass

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/")
def root():
    return {"status": "ok", "env": settings.ENV}
