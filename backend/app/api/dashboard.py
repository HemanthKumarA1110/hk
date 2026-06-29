from datetime import datetime
from fastapi import APIRouter
from sqlmodel import select
from collections import Counter
from app.db.session import Session, engine
from app.models import Portfolio, Trade, Position, Strategy
from app.api.serializers import DashboardOverview

router = APIRouter()

@router.get('/dashboard/overview', response_model=DashboardOverview)
def dashboard_overview():
    with Session(engine) as session:
        portfolio = session.exec(select(Portfolio)).first()
        trades = session.exec(select(Trade)).all()
        positions = session.exec(select(Position).where(Position.status == 'open')).all()
        enabled_strategies = session.exec(select(Strategy).where(Strategy.enabled == True)).all()

    total_trades = len(trades)
    wins = sum(
        1
        for t in trades
        if getattr(t, 'status', '').lower() == 'filled' and getattr(t, 'qty', 0) and getattr(t, 'price', 0) >= 0
    )
    win_rate = round(wins / total_trades * 100, 2) if total_trades else 0.0
    current_open_trades = len(positions)
    portfolio_capital = portfolio.capital if portfolio else 0.0
    portfolio_daily_pnl = portfolio.daily_pnl if portfolio else 0.0
    current_exposure = sum(p.qty * p.entry_price for p in positions) if positions else 0.0
    max_daily_loss = abs(portfolio_daily_pnl) if portfolio else 0.0
    risk_status = 'ok' if max_daily_loss <= portfolio_capital * 0.05 else 'breach'

    symbol_counts = Counter(t.symbol for t in trades)
    top_symbol = symbol_counts.most_common(1)[0][0] if symbol_counts else 'N/A'
    total_volume = sum(t.qty for t in trades)
    market_mood = 'bullish' if portfolio_daily_pnl > 0 else 'bearish' if portfolio_daily_pnl < 0 else 'neutral'

    equity_curve = [
        round(portfolio_capital - portfolio_daily_pnl + (portfolio_daily_pnl * i) / 9, 2)
        for i in range(10)
    ] if portfolio else [100000.0]
    recent_trades = [
        {
            'symbol': trade.symbol,
            'side': trade.side,
            'qty': trade.qty,
            'price': trade.price,
            'status': trade.status,
            'timestamp': trade.ts.isoformat() if trade.ts else None,
        }
        for trade in sorted(trades, key=lambda t: t.ts, reverse=True)[:5]
    ]

    return DashboardOverview(
        total_capital=portfolio_capital,
        available_margin=portfolio.available_margin if portfolio else 0.0,
        daily_pnl=portfolio_daily_pnl,
        weekly_pnl=portfolio.weekly_pnl if portfolio else 0.0,
        monthly_pnl=portfolio.monthly_pnl if portfolio else 0.0,
        win_rate=win_rate,
        risk_reward_ratio=2.0,
        total_trades=total_trades,
        current_open_trades=current_open_trades,
        max_drawdown=0.0,
        roi=portfolio.roi if portfolio else 0.0,
        risk={
            'current_exposure': current_exposure,
            'max_daily_loss': max_daily_loss,
            'strategy_count': len(enabled_strategies),
            'risk_status': risk_status,
        },
        market_summary={
            'daily_volume': total_volume,
            'top_symbol': top_symbol,
            'market_mood': market_mood,
        },
        equity_curve=equity_curve,
        recent_trades=recent_trades,
        last_updated=datetime.utcnow().isoformat() + 'Z',
    )
