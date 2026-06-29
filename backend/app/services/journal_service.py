from datetime import datetime
from typing import List
from sqlmodel import select
from app.db.session import Session, engine
from app.models import Portfolio, Position, Alert

class JournalService:
    def __init__(self):
        self.engine = engine

    def create_portfolio(self, user_id: int, capital: float, available_margin: float) -> Portfolio:
        portfolio = Portfolio(
            user_id=user_id,
            capital=capital,
            available_margin=available_margin,
            daily_pnl=0.0,
            weekly_pnl=0.0,
            monthly_pnl=0.0,
            roi=0.0,
        )
        with Session(self.engine) as session:
            session.add(portfolio)
            session.commit()
            session.refresh(portfolio)
        return portfolio

    def update_portfolio(self, portfolio_id: int, **updates) -> Portfolio:
        with Session(self.engine) as session:
            portfolio = session.get(Portfolio, portfolio_id)
            if not portfolio:
                raise ValueError("Portfolio not found")
            for attr, value in updates.items():
                setattr(portfolio, attr, value)
            portfolio.updated_at = datetime.utcnow()
            session.add(portfolio)
            session.commit()
            session.refresh(portfolio)
        return portfolio

    def list_portfolios(self) -> List[Portfolio]:
        with Session(self.engine) as session:
            return session.exec(select(Portfolio)).all()

    def create_position(self, order_id: int, symbol: str, side: str, qty: int, entry_price: float, stoploss: float, target: float) -> Position:
        position = Position(
            order_id=order_id,
            symbol=symbol,
            side=side,
            qty=qty,
            entry_price=entry_price,
            stoploss=stoploss,
            target=target,
            status='open',
        )
        with Session(self.engine) as session:
            session.add(position)
            session.commit()
            session.refresh(position)
        return position

    def close_position(self, position_id: int, exit_price: float) -> Position:
        with Session(self.engine) as session:
            position = session.get(Position, position_id)
            if not position:
                raise ValueError("Position not found")
            position.closed_at = datetime.utcnow()
            position.status = 'closed'
            position.pnl = (exit_price - position.entry_price) * position.qty if position.side == 'BUY' else (position.entry_price - exit_price) * position.qty
            session.add(position)
            session.commit()
            session.refresh(position)
        return position

    def list_positions(self) -> List[Position]:
        with Session(self.engine) as session:
            return session.exec(select(Position)).all()

    def create_alert(self, alert_type: str, symbol: str, message: str) -> Alert:
        alert = Alert(alert_type=alert_type, symbol=symbol, message=message)
        with Session(self.engine) as session:
            session.add(alert)
            session.commit()
            session.refresh(alert)
        return alert

    def list_alerts(self) -> List[Alert]:
        with Session(self.engine) as session:
            return session.exec(select(Alert)).all()

journal_service = JournalService()
