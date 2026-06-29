"""Run a backtest from CSV data and print metrics."""
import argparse
import pandas as pd
from app.backtest import Backtester
from app.strategies import scalping, intraday, swing

STRATEGIES = {
    'scalping': scalping.generate_signals,
    'intraday': intraday.generate_signals,
    'swing': swing.generate_signals,
}


def run(path: str, strategy: str, symbol: str = 'UNKNOWN'):
    df = pd.read_csv(path, parse_dates=['timestamp'])
    df = df.rename(columns={'timestamp': 'time'})
    df.set_index('time', inplace=True)
    backtester = Backtester(initial_capital=100000, risk_pct=1.0)
    result = backtester.run(df, STRATEGIES[strategy], symbol=symbol)
    print('Initial capital:', result['initial_capital'])
    print('Final capital:', result['final_capital'])
    print('Total trades:', result['total_trades'])
    print('Win rate:', result['win_rate'], '%')
    print('Max drawdown:', result['max_drawdown'], '%')
    print('Trades:')
    for trade in result['trades']:
        print(trade)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--strategy', required=True, choices=STRATEGIES.keys())
    p.add_argument('--file', required=True)
    p.add_argument('--symbol', default='UNKNOWN')
    args = p.parse_args()
    run(args.file, args.strategy, args.symbol)
