from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from app.services.broker_service import broker_service
from app.services.risk_engine import risk_engine

class LiveOrderRequest(BaseModel):
    symbol: str
    side: str
    qty: int
    price: float
    order_type: str = 'market'

class LiveOrderResponse(BaseModel):
    status: str
    order_id: Optional[str] = None
    symbol: str
    side: str
    qty: int
    price: float
    message: str

class BrokerStatusResponse(BaseModel):
    connected: bool
    user_id: Optional[str] = None
    client_id: Optional[str] = None
    session_token: bool
    refresh_token: bool
    base_url: str
    error: Optional[str] = None

class BrokerQuoteResponse(BaseModel):
    symbol: str
    last_price: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[int] = None
    raw: dict

class BrokerTrade(BaseModel):
    order_id: Optional[str]
    symbol: str
    side: str
    qty: int
    price: float
    status: str
    timestamp: Optional[str]

router = APIRouter()

@router.post('/broker/order', response_model=LiveOrderResponse)
def place_live_order(payload: LiveOrderRequest):
    if not risk_engine.can_trade():
        raise HTTPException(status_code=403, detail='Risk limits blocked live order')
    result = broker_service.execute_order(
        symbol=payload.symbol,
        side=payload.side,
        qty=payload.qty,
        price=payload.price,
        order_type=payload.order_type,
    )
    return {
        'status': result.get('status', 'unknown'),
        'order_id': result.get('order_id'),
        'symbol': payload.symbol,
        'side': payload.side,
        'qty': payload.qty,
        'price': payload.price,
        'message': result.get('message', result.get('error', 'order submitted')),
    }

@router.get('/broker/status', response_model=BrokerStatusResponse)
def broker_status():
    result = broker_service.get_broker_status()
    return {
        'connected': result.get('connected', False),
        'user_id': result.get('user_id'),
        'client_id': result.get('client_id'),
        'session_token': result.get('session_token', False),
        'refresh_token': result.get('refresh_token', False),
        'base_url': result.get('base_url', ''),
        'error': result.get('error'),
    }

@router.get('/broker/quote', response_model=BrokerQuoteResponse)
def broker_quote(symbol: str = Query(..., description='Symbol to fetch live quote for')):
    result = broker_service.get_live_quote(symbol)
    return {
        'symbol': symbol,
        'last_price': result.get('last_price'),
        'bid': result.get('bid'),
        'ask': result.get('ask'),
        'volume': result.get('volume'),
        'raw': result,
    }

@router.get('/broker/trades', response_model=List[BrokerTrade])
def broker_trades():
    return broker_service.list_trades()
