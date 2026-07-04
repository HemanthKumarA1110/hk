import time

from datetime import date

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from trading_shared.admin.overview import AdminOverviewAggregator
from trading_shared.db.session import get_db, init_db
from trading_shared.middleware.auth import get_current_user
from trading_shared.models import User
from trading_shared.service_factory import create_service_app

app = create_service_app("admin-dashboard", "Institutional dashboard BFF and overview aggregation")
router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/overview")
def overview(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return AdminOverviewAggregator(db).overview()


@router.get("/equity-curve")
def equity_curve(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return AdminOverviewAggregator(db).equity_curve()


@router.get("/journal")
def journal(
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    engine: str | None = Query(default=None, description="scalping | intraday | swing"),
    status: str | None = Query(default=None, description="open | closed | filled | rejected_by_risk"),
    profitable: bool | None = Query(default=None, description="True=profit only, False=loss only"),
    limit: int = Query(default=500, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    return AdminOverviewAggregator(db).journal_entries(
        current_user.id,
        from_date=from_date,
        to_date=to_date,
        engine=engine,
        status=status,
        profitable=profitable,
        limit=limit,
    )


@router.get("/journal/export")
def journal_export(
    from_date: date | None = Query(default=None),
    to_date: date | None = Query(default=None),
    engine: str | None = Query(default=None),
    status: str | None = Query(default=None),
    profitable: bool | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    data = AdminOverviewAggregator(db).journal_entries(
        current_user.id,
        from_date=from_date,
        to_date=to_date,
        engine=engine,
        status=status,
        profitable=profitable,
        limit=limit,
    )
    headers_row = [
        "Symbol",
        "Engine",
        "Side",
        "Quantity",
        "Lots",
        "P&L",
        "AI Score",
        "Status",
        "Entry DateTime",
        "Exit DateTime",
        "Source",
    ]

    def cell(value) -> str:
        text = "" if value is None else str(value)
        return '"' + text.replace('"', '""') + '"'

    lines = [",".join(headers_row)]
    for row in data.get("entries") or []:
        lines.append(
            ",".join(
                [
                    cell(row.get("symbol")),
                    cell(row.get("engine")),
                    cell(row.get("side")),
                    cell(row.get("qty")),
                    cell(row.get("lots")),
                    cell(row.get("pnl")),
                    cell(row.get("ai_score")),
                    cell(row.get("status")),
                    cell(row.get("entry_datetime")),
                    cell(row.get("exit_datetime")),
                    cell(row.get("source")),
                ]
            )
        )
    body = "\ufeff" + "\n".join(lines)
    filename = f"trade-journal-{date.today().isoformat()}.csv"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/backtest/preview")
def backtest_preview(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict:
    return AdminOverviewAggregator(db).backtest_preview()


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


@app.on_event("startup")
def on_startup() -> None:
    wait_for_db()
