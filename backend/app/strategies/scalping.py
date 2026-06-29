import pandas as pd
from app.schemas import SignalPayload
from app.strategies.ta_utils import ema, rsi, vwap


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['ema9'] = ema(df['close'], length=9)
    df['ema20'] = ema(df['close'], length=20)
    df['rsi'] = rsi(df['close'], length=14)
    df['vwap'] = vwap(df['high'], df['low'], df['close'], df['volume'])
    df['vol_breakout'] = df['volume'] > df['volume'].rolling(20).mean() * 1.5
    return df


def build_signal(symbol: str, side: str, row: pd.Series, prev: pd.Series) -> SignalPayload:
    if side == 'BUY':
        stoploss = float(prev['low'])
        target = float(row['close']) + 2 * (float(row['close']) - stoploss)
        trailing_stop = float(prev['low'])
    else:
        stoploss = float(prev['high'])
        target = float(row['close']) - 2 * (stoploss - float(row['close']))
        trailing_stop = float(prev['high'])

    return SignalPayload(
        strategy='scalping',
        symbol=symbol,
        side=side,
        entry=round(float(row['close']), 2),
        stoploss=round(stoploss, 2),
        targets=[round(target, 2)],
        trailing_stop=round(trailing_stop, 2),
        confidence=0.75,
        timeframe='1m',
        risk_reward=2.0,
    )


def generate_signals(df: pd.DataFrame, symbol: str = 'UNKNOWN'):
    df = compute_indicators(df)
    signals = []
    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        buy = (
            row['ema9'] > row['ema20'] and
            row['close'] > row['vwap'] and
            row['rsi'] > 60 and
            row['vol_breakout'] and
            row['close'] > prev['high']
        )
        sell = (
            row['ema9'] < row['ema20'] and
            row['close'] < row['vwap'] and
            row['rsi'] < 40 and
            row['vol_breakout'] and
            row['close'] < prev['low']
        )
        if buy:
            signals.append(build_signal(symbol, 'BUY', row, prev))
        elif sell:
            signals.append(build_signal(symbol, 'SELL', row, prev))
    return signals
