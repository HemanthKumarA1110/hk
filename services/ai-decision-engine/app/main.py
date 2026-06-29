import asyncio
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from trading_shared.config import get_settings
from trading_shared.db.session import SessionLocal, get_db, init_db
from trading_shared.middleware.auth import get_current_user, require_roles
from trading_shared.models import TradeJournalEntry, User, UserRole
from trading_shared.schemas.ai import AIRunResponse, JournalEntryRequest, JournalInsightsResponse
from trading_shared.service_factory import create_service_app
from trading_shared.ai.journal_analyzer import JournalAnalyzer
from trading_shared.ai.learning import AdaptiveLearner
from trading_shared.ai.orchestrator import AIOrchestrator

logger = logging.getLogger(__name__)
settings = get_settings()
app = create_service_app("ai-decision-engine", "AI trade decision scoring and adaptive learning")
router = APIRouter(prefix="/api/v1/ai", tags=["ai"])

_runner_task: asyncio.Task | None = None


@router.post("/evaluate", response_model=AIRunResponse)
def evaluate_all(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
) -> dict:
    return AIOrchestrator(db).run()


@router.get("/decisions", response_model=AIRunResponse)
def latest_decisions(_: User = Depends(get_current_user)) -> dict:
    cached = AIOrchestrator.get_cached()
    if not cached.get("decisions"):
        return {
            "generated_at": "",
            "decisions": [],
            "approved": [],
            "rejected_count": 0,
            "journal_insights": {},
            "weights": {},
        }
    return cached


@router.get("/decisions/{symbol}")
def decision_for_symbol(symbol: str, _: User = Depends(get_current_user)) -> dict:
    cached = AIOrchestrator.get_cached()
    matches = [d for d in cached.get("decisions", []) if d.get("symbol") == symbol]
    if not matches:
        raise HTTPException(status_code=404, detail="No AI decision for symbol")
    return matches[0]


@router.get("/journal/insights", response_model=JournalInsightsResponse)
def journal_insights(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return JournalAnalyzer(db).analyze()


@router.post("/journal/entries")
def create_journal_entry(
    payload: JournalEntryRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN, UserRole.TRADER)),
) -> dict:
    entry = TradeJournalEntry(
        symbol=payload.symbol,
        engine=payload.engine,
        side=payload.side,
        entry_price=payload.entry_price,
        exit_price=payload.exit_price,
        current_price=payload.current_price,
        qty=payload.qty,
        pnl=payload.pnl,
        status=payload.status,
        features_json=json.dumps(payload.features),
        metadata_json=json.dumps(payload.metadata),
        ai_score=payload.ai_score,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"id": entry.id, "status": "saved"}


@router.post("/learn")
def trigger_learning(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(UserRole.ADMIN)),
) -> dict:
    import redis
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return AdaptiveLearner(db, client).learn_from_journal()


@router.get("/weights")
def get_weights(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    import redis
    client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    learner = AdaptiveLearner(db, client)
    return {"weights": learner.weights, "threshold": settings.AI_DECISION_THRESHOLD}


app.include_router(router)


def wait_for_db(retries: int = 20, delay_seconds: int = 2) -> None:
    for attempt in range(1, retries + 1):
        try:
            init_db()
            return
        except Exception:
            if attempt == retries:
                raise
            time.sleep(delay_seconds)


def seed_demo_journal(db: Session) -> None:
    if db.query(TradeJournalEntry).first():
        return
    samples = [
        TradeJournalEntry(symbol="SBIN-EQ", engine="intraday", side="BUY", entry_price=800, exit_price=812, qty=10, pnl=120, status="closed", features_json='{"trend":80,"volume":70,"risk_reward":75}', metadata_json='{"mistake":""}', ai_score=78),
        TradeJournalEntry(symbol="RELIANCE-EQ", engine="swing", side="BUY", entry_price=2800, exit_price=2750, qty=5, pnl=-250, status="closed", features_json='{"trend":45,"volume":50,"risk_reward":40}', metadata_json='{"mistake":"early_entry"}', ai_score=52),
        TradeJournalEntry(symbol="NIFTY-OPT", engine="scalping", side="BUY", entry_price=24000, exit_price=24025, qty=50, pnl=1250, status="closed", features_json='{"trend":85,"oi":80,"greeks":75}', metadata_json='{"mistake":""}', ai_score=82),
    ]
    db.add_all(samples)
    db.commit()
    logger.info("Seeded demo trade journal entries for adaptive learning")


async def _ai_loop() -> None:
    await asyncio.sleep(8)
    while True:
        try:
            db = SessionLocal()
            try:
                orchestrator = AIOrchestrator(db)
                orchestrator.decision_engine.enter_threshold = settings.AI_DECISION_THRESHOLD
                orchestrator.run()
            finally:
                db.close()
        except Exception:
            logger.exception("AI loop failed")
        await asyncio.sleep(60)


@app.on_event("startup")
async def on_startup() -> None:
    global _runner_task
    wait_for_db()
    db = SessionLocal()
    try:
        seed_demo_journal(db)
    finally:
        db.close()
    _runner_task = asyncio.create_task(_ai_loop())
