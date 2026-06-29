import pandas as pd
from app.strategies import scalping, intraday, swing


def sample_df():
    data = {
        'timestamp': pd.date_range(start='2026-01-01 09:15', periods=10, freq='T'),
        'open': [100, 101, 102, 103, 102, 101, 102, 103, 104, 105],
        'high': [101, 102, 103, 104, 103, 102, 103, 104, 105, 106],
        'low': [99, 100, 101, 102, 101, 100, 101, 102, 103, 104],
        'close': [100, 101, 102, 103, 102, 101, 102, 103, 104, 105],
        'volume': [1000, 1200, 1500, 2000, 1100, 1300, 1400, 1600, 1800, 1900],
    }
    df = pd.DataFrame(data)
    df.set_index('timestamp', inplace=True)
    return df


def test_scalping_signals():
    df = sample_df()
    signals = scalping.generate_signals(df, symbol='NIFTY')
    assert isinstance(signals, list)
    for signal in signals:
        assert signal.strategy == 'scalping'
        assert signal.side in ['BUY', 'SELL']


def test_intraday_signals():
    df = sample_df()
    signals = intraday.generate_signals(df, symbol='NIFTY', target_rr=2.0)
    assert isinstance(signals, list)
    for signal in signals:
        assert signal.strategy == 'intraday'


def test_swing_signals():
    df = sample_df()
    signals = swing.generate_signals(df, symbol='RELIANCE')
    assert isinstance(signals, list)
