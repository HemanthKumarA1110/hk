from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services.journal_service import journal_service

class PortfolioRequest(BaseModel):
    user_id: int
    capital: float
    available_margin: float

class PositionRequest(BaseModel):
    order_id: int
    symbol: str
    side: str
    qty: int
    entry_price: float
    stoploss: float
    target: float

class ClosePositionRequest(BaseModel):
    position_id: int
    exit_price: float

class AlertRequest(BaseModel):
    alert_type: str
    symbol: str
    message: str

router = APIRouter()

@router.post('/journal/portfolio')
def create_portfolio(payload: PortfolioRequest):
    return journal_service.create_portfolio(
        user_id=payload.user_id,
        capital=payload.capital,
        available_margin=payload.available_margin,
    )

@router.get('/journal/portfolios')
def list_portfolios():
    return journal_service.list_portfolios()

@router.post('/journal/position')
def create_position(payload: PositionRequest):
    return journal_service.create_position(
        order_id=payload.order_id,
        symbol=payload.symbol,
        side=payload.side,
        qty=payload.qty,
        entry_price=payload.entry_price,
        stoploss=payload.stoploss,
        target=payload.target,
    )

@router.post('/journal/position/close')
def close_position(payload: ClosePositionRequest):
    try:
        return journal_service.close_position(payload.position_id, payload.exit_price)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

@router.get('/journal/positions')
def list_positions():
    return journal_service.list_positions()

@router.post('/journal/alert')
def create_alert(payload: AlertRequest):
    return journal_service.create_alert(
        alert_type=payload.alert_type,
        symbol=payload.symbol,
        message=payload.message,
    )

@router.get('/journal/alerts')
def list_alerts():
    return journal_service.list_alerts()
