from datetime import datetime
from typing import Optional
from app.models.orders import Order, PositionEntry
from app.services.risk_engine import RiskEngine

class PaperTradeService:
    def __init__(self, equity: float = 100000.0):
        self.risk_engine = RiskEngine(equity=equity)
        self.orders = []
        self.positions = []

    def place_order(self, symbol: str, side: str, qty: int, price: float, mode: str = 'paper', order_type: str = 'market') -> Order:
        order = Order(
            symbol=symbol,
            side=side,
            qty=qty,
            price=price,
            status='filled' if mode == 'paper' else 'pending',
            mode=mode,
            order_type=order_type,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        self.orders.append(order)
        if mode == 'paper':
            self._create_position(order)
        return order

    def _create_position(self, order: Order):
        position = PositionEntry(
            order_id=order.id,
            symbol=order.symbol,
            side=order.side,
            qty=order.qty,
            entry_price=order.price,
            stoploss=0.0,
            target=0.0,
            status='open',
            opened_at=datetime.utcnow(),
        )
        self.positions.append(position)
        return position

    def square_off(self, position_id: int, exit_price: float):
        position = next((p for p in self.positions if p.id == position_id), None)
        if not position:
            raise ValueError('Position not found')
        position.closed_at = datetime.utcnow()
        position.status = 'closed'
        position.pnl = (exit_price - position.entry_price) * position.qty if position.side == 'BUY' else (position.entry_price - exit_price) * position.qty
        return position

paper_trade_service = PaperTradeService()
