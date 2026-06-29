from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app.services.paper_trade import paper_trade_service

class PaperOrderRequest(BaseModel):
    symbol: str
    side: str
    qty: int
    price: float
    order_type: str = 'market'

class PaperOrderResponse(BaseModel):
    symbol: str
    side: str
    qty: int
    price: float
    status: str
    mode: str

router = APIRouter()

@router.post('/paper/order', response_model=PaperOrderResponse)
def place_paper_order(payload: PaperOrderRequest):
    order = paper_trade_service.place_order(
        symbol=payload.symbol,
        side=payload.side,
        qty=payload.qty,
        price=payload.price,
        mode='paper',
        order_type=payload.order_type,
    )
    return {
        'symbol': order.symbol,
        'side': order.side,
        'qty': order.qty,
        'price': order.price,
        'status': order.status,
        'mode': order.mode,
    }

@router.get('/paper/positions')
def get_paper_positions():
    return [p.dict() for p in paper_trade_service.positions]

@router.get('/paper/orders')
def get_paper_orders():
    return [o.dict() for o in paper_trade_service.orders]
