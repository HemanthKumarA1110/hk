from fastapi import APIRouter, HTTPException
from app.schemas import Health, SignalCreate
from app.api.serializers import BacktestRequest, BacktestResult, SignalResponse
from app.backtest import Backtester
from app.data_loader import load_market_data
from app.strategies import scalping, intraday, swing

router = APIRouter()

@router.get('/health', response_model=Health)
def health():
    return {"status": "ok"}

@router.post('/signals', response_model=SignalResponse)
def create_signal(payload: SignalCreate):
    # placeholder: persist signal and queue execution
    return {
        "strategy": "manual",
        "symbol": payload.symbol,
        "side": payload.side,
        "entry": payload.entry,
        "stoploss": payload.stoploss or 0.0,
        "targets": [payload.target] if payload.target else [],
        "trailing_stop": None,
        "confidence": payload.confidence,
        "timeframe": None,
        "risk_reward": None,
    }

@router.post('/backtest', response_model=BacktestResult)
def backtest(payload: BacktestRequest):
    strategy_map = {
        'scalping': scalping.generate_signals,
        'intraday': intraday.generate_signals,
        'swing': swing.generate_signals,
    }
    if payload.strategy not in strategy_map:
        raise HTTPException(status_code=400, detail='Unsupported strategy')

    try:
        df = load_market_data(payload.symbol, payload.timeframe)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    backtester = Backtester(initial_capital=100000.0, risk_pct=payload.risk_pct)
    result = backtester.run(
        df,
        strategy_map[payload.strategy],
        symbol=payload.symbol,
        max_loss_per_trade_pct=payload.max_loss_per_trade_pct,
        max_daily_loss_pct=payload.max_daily_loss_pct,
        max_trades_per_day=payload.max_trades_per_day,
    )
    return result
