"""Run a strategy on CSV OHLCV data for quick testing.
Usage: python run_strategy.py --strategy scalping --file data/NIFTY_1m.csv
"""
import argparse
import pandas as pd
from app.strategies import scalping, intraday, swing

STRATS = {
    'scalping': scalping,
    'intraday': intraday,
    'swing': swing,
}

def run(path: str, strategy: str):
    df = pd.read_csv(path, parse_dates=['timestamp'])
    df = df.rename(columns={'timestamp': 'time', 'open': 'open', 'high': 'high', 'low': 'low', 'close': 'close', 'volume': 'volume'})
    df.set_index('time', inplace=True)
    module = STRATS[strategy]
    signals = module.generate_signals(df)
    print(signals.head(10))

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--strategy', required=True)
    p.add_argument('--file', required=True)
    args = p.parse_args()
    run(args.file, args.strategy)
