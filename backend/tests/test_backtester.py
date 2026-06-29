import pandas as pd
from app.backtest import Backtester
from app.strategies import scalping


def sample_df():
    data = {
        'timestamp': pd.date_range(start='2026-01-01 09:15', periods=20, freq='T'),
        'open': [100 + i for i in range(20)],
        'high': [101 + i for i in range(20)],
        'low': [99 + i for i in range(20)],
        'close': [100 + i for i in range(20)],
        'volume': [1000 + 50 * i for i in range(20)],
    }
    df = pd.DataFrame(data)
    df.set_index('timestamp', inplace=True)
    return df


def test_backtester_runs():
    df = sample_df()
    backtester = Backtester(initial_capital=100000, risk_pct=1.0)
    result = backtester.run(df, scalping.generate_signals, symbol='NIFTY')
    assert result['initial_capital'] == 100000
    assert 'equity_curve' in result
    assert 'max_drawdown' in result
    assert isinstance(result['trades'], list)
