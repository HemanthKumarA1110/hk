import logging

from app.worker import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="health.ping")
def ping() -> dict:
    return {"status": "ok", "worker": "celery-worker"}


@celery_app.task(name="ai.evaluate_all")
def evaluate_ai_decisions() -> dict:
    from trading_shared.config import get_settings
    from trading_shared.db.session import SessionLocal
    from trading_shared.ai.orchestrator import AIOrchestrator

    settings = get_settings()
    db = SessionLocal()
    try:
        orchestrator = AIOrchestrator(db)
        orchestrator.decision_engine.enter_threshold = settings.AI_DECISION_THRESHOLD
        return orchestrator.run()
    finally:
        db.close()


@celery_app.task(name="strategies.run_all")
def run_all_strategies() -> dict:
    from trading_shared.db.session import SessionLocal
    from trading_shared.strategies.orchestrator import StrategyOrchestrator

    db = SessionLocal()
    try:
        return StrategyOrchestrator(db).run_all()
    finally:
        db.close()


@celery_app.task(name="market.run_scanner")
def run_market_scanner() -> dict:
    import redis
    from trading_shared.config import get_settings
    from trading_shared.db.session import SessionLocal
    from trading_shared.market.redis_bus import MarketRedisBus
    from trading_shared.market.scanner import MarketScanner
    from trading_shared.market.scrip_master import ScripMasterService

    settings = get_settings()
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    bus = MarketRedisBus(settings.REDIS_URL)
    scrip = ScripMasterService(redis_client)
    if not scrip.ensure_loaded():
        import asyncio

        asyncio.run(scrip.refresh(force=True))
    scanner = MarketScanner(bus, scrip)
    db = SessionLocal()
    try:
        return scanner.run_scan(db)
    finally:
        db.close()


@celery_app.task(name="auto_trading.run")
def run_auto_trading() -> dict:
    from trading_shared.config import get_settings
    from trading_shared.db.session import SessionLocal
    from trading_shared.execution.auto_trading import run_auto_trading_sync

    db = SessionLocal()
    try:
        return run_auto_trading_sync(db, get_settings().REDIS_URL)
    finally:
        db.close()


@celery_app.task(name="backtest.run")
def run_backtest_job(run_id: int) -> dict:
    from trading_shared.backtest.orchestrator import BacktestOrchestrator
    from trading_shared.db.session import SessionLocal

    db = SessionLocal()
    try:
        return BacktestOrchestrator(db).execute_run(run_id)
    except Exception as exc:
        return {"run_id": run_id, "status": "failed", "error": str(exc)}
    finally:
        db.close()
