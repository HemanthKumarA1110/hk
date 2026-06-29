from fastapi import APIRouter
from app.services.risk_engine import risk_engine

router = APIRouter()

@router.get('/risk/status')
def risk_status():
    return {
        'equity': risk_engine.equity,
        'max_loss_per_trade_pct': risk_engine.max_loss_per_trade_pct,
        'max_daily_loss_pct': risk_engine.max_daily_loss_pct,
        'max_trades_per_day': risk_engine.max_trades_per_day,
        'daily_loss': risk_engine.daily_loss,
        'trade_count': risk_engine.trade_count,
    }
