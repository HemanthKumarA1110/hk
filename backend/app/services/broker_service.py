from sqlmodel import select
from app.broker.angel_one import AngelOneClient
from app.services.risk_engine import RiskEngine
from app.models import Trade
from app.db.session import Session, engine

class BrokerService:
    def __init__(self, equity: float = 100000.0):
        self.client = AngelOneClient()
        self.risk_engine = RiskEngine(equity=equity)

    def execute_order(self, symbol: str, side: str, qty: int, price: float, order_type: str = 'market') -> dict:
        order_payload = {
            'symbol': symbol,
            'side': side,
            'qty': qty,
            'price': price,
            'order_type': order_type,
        }
        result = self.client.place_order_sync(order_payload)
        with Session(engine) as session:
            trade = Trade(
                order_id=result.get('order_id'),
                signal_id=None,
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                status=result.get('status', 'unknown'),
            )
            session.add(trade)
            session.commit()
            session.refresh(trade)
        return result

    def get_broker_status(self) -> dict:
        return self.client.get_account_status_sync()

    def get_live_quote(self, symbol: str) -> dict:
        return self.client.get_live_quote_sync(symbol)

    def list_trades(self) -> list[dict]:
        with Session(engine) as session:
            trades = session.exec(select(Trade)).all()
        return [
            {
                'order_id': t.order_id,
                'symbol': t.symbol,
                'side': t.side,
                'qty': t.qty,
                'price': t.price,
                'status': t.status,
                'timestamp': t.ts.isoformat() if t.ts else None,
            }
            for t in trades
        ]

broker_service = BrokerService()
