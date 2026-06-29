import os
import pandas as pd
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')


def load_market_data(symbol: str, timeframe: str, source: Optional[str] = None) -> pd.DataFrame:
    """Load historical OHLCV data for a symbol/timeframe from the local data directory."""
    filename = source or f"{symbol}_{timeframe}.csv"
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        raise FileNotFoundError(f"Market data file not found: {path}")
    df = pd.read_csv(path, parse_dates=['timestamp'])
    df = df.rename(columns={
        'timestamp': 'time',
        'open': 'open',
        'high': 'high',
        'low': 'low',
        'close': 'close',
        'volume': 'volume',
    })
    df.set_index('time', inplace=True)
    return df
