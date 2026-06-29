import pandas as pd
from app.schemas import SignalPayload
from app.strategies.ta_utils import ema, rsi


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['ema20'] = ema(df['close'], length=20)
    df['ema50'] = ema(df['close'], length=50)
    df['rsi'] = rsi(df['close'], length=14)
    df['supertrend'] = ((df['high'] + df['low'] + df['close']) / 3).rolling(10).mean() - ((df['high'] + df['low'] + df['close']) / 3).rolling(20).mean()
    df['vol_conf'] = df['volume'] > df['volume'].rolling(20).mean()
    return df


def build_signal(symbol: str, side: str, row: pd.Series, prev: pd.Series, target_rr: float) -> SignalPayload:
    if side == 'BUY':
        stoploss = float(prev['low'])
        target = float(row['close']) + target_rr * (float(row['close']) - stoploss)
        trailing_stop = float(prev['low'])
    else:
        stoploss = float(prev['high'])
        target = float(row['close']) - target_rr * (stoploss - float(row['close']))
        trailing_stop = float(prev['high'])

    return SignalPayload(
        strategy='intraday',
        symbol=symbol,
        side=side,
        entry=round(float(row['close']), 2),
        stoploss=round(stoploss, 2),
        targets=[round(target, 2)],
        trailing_stop=round(trailing_stop, 2),
        confidence=0.7,
        timeframe='15m',
        risk_reward=target_rr,
    )


def generate_signals(df: pd.DataFrame, symbol: str = 'UNKNOWN', target_rr: float = 2.0):
    df = compute_indicators(df)
    signals = []
    for i in range(1, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        buy = (
            row['ema20'] > row['ema50'] and
            row['supertrend'] > 0 and
            55 <= row['rsi'] <= 70 and
            row['close'] > prev['high'] and
            row['vol_conf']
        )
        sell = (
            row['ema20'] < row['ema50'] and
            row['supertrend'] < 0 and
            30 <= row['rsi'] <= 45 and
            row['close'] < prev['low'] and
            row['vol_conf']
        )
        if buy:
            signals.append(build_signal(symbol, 'BUY', row, prev, target_rr))
        elif sell:
            signals.append(build_signal(symbol, 'SELL', row, prev, target_rr))
    return signals
