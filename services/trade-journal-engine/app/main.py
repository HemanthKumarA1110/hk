from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from trading_shared.db.session import get_db, init_db
from trading_shared.middleware.auth import get_current_user
from trading_shared.models import TradeJournalEntry, User
from trading_shared.service_factory import create_service_app

app = create_service_app("trade-journal-engine", "Trade journal CRUD (Phase 6)")
router = APIRouter(prefix="/api/v1/journal", tags=["journal"])


@router.get("/entries")
def list_entries(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    rows = db.query(TradeJournalEntry).order_by(TradeJournalEntry.created_at.desc()).limit(50).all()
    return {
        "entries": [
            {
                "id": r.id,
                "symbol": r.symbol,
                "engine": r.engine,
                "pnl": r.pnl,
                "status": r.status,
                "ai_score": r.ai_score,
            }
            for r in rows
        ]
    }


app.include_router(router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
