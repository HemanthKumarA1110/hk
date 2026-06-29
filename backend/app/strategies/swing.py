import pandas as pd
from app.schemas import SignalPayload
from app.strategies.ta_utils import ema, rsi, macd


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['ema20'] = ema(df['close'], length=20)
    df['ema50'] = ema(df['close'], length=50)
    df['ema200'] = ema(df['close'], length=200)
    macd_df = macd(df['close'])
    df['macd'] = macd_df['MACD']
    df['macd_signal'] = macd_df['MACDs']
    df['rsi'] = rsi(df['close'], length=14)
    df['adx'] = ((df['high'] - df['low']).rolling(14).mean() / df['close']) * 100
    df['vol_break'] = df['volume'] > df['volume'].rolling(50).mean() * 1.5
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
        strategy='swing',
        symbol=symbol,
        side=side,
        entry=round(float(row['close']), 2),
        stoploss=round(stoploss, 2),
        targets=[round(target, 2)],
        trailing_stop=round(trailing_stop, 2),
        confidence=0.8,
        timeframe='1d',
        risk_reward=2.0,
    )


def generate_signals(df: pd.DataFrame, symbol: str = 'UNKNOWN'):
    df = compute_indicators(df)
    signals = []
    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        buy = (
            row['ema20'] > row['ema50'] > row['ema200'] and
            row['macd'] > row['macd_signal'] and
            row['rsi'] > 55 and
            row['adx'] > 25 and
            row['vol_break']
        )
        sell = (
            row['ema20'] < row['ema50'] < row['ema200'] and
            row['macd'] < row['macd_signal'] and
            row['rsi'] < 45 and
            row['vol_break']
        )
        if buy:
            signals.append(build_signal(symbol, 'BUY', row, prev))
        elif sell:
            signals.append(build_signal(symbol, 'SELL', row, prev))
    return signals
