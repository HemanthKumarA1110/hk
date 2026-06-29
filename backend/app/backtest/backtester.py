"""Simple backtesting harness skeleton.
Feed historic candles, apply strategy function, track equity curve and trades.
"""
from typing import List, Dict, Callable
from dataclasses import dataclass, asdict
from datetime import date
from app.services.risk_engine import RiskEngine

@dataclass
class BacktestTrade:
    entry_ts: str
    exit_ts: str
    side: str
    symbol: str
    entry_price: float
    exit_price: float
    qty: int
    pnl: float
    return_pct: float
    stoploss: float
    target: float

class Backtester:
    def __init__(self, initial_capital: float = 100000.0, risk_pct: float = 1.0):
        self.initial_capital = initial_capital
        self.capital = initial_capital
        self.risk_pct = risk_pct
        self.equity_curve = []
        self.trades: List[BacktestTrade] = []
        self.risk_engine = RiskEngine(equity=initial_capital)

    def run(
        self,
        df,
        strategy_fn: Callable,
        symbol: str = 'UNKNOWN',
        max_loss_per_trade_pct: float = 1.0,
        max_daily_loss_pct: float = 5.0,
        max_trades_per_day: int = 10,
    ) -> Dict:
        self.capital = self.initial_capital
        self.equity_curve = []
        self.trades = []
        self.risk_engine = RiskEngine(equity=self.initial_capital)
        self.risk_engine.set_limits(
            max_loss_per_trade_pct=max_loss_per_trade_pct,
            max_daily_loss_pct=max_daily_loss_pct,
            max_trades_per_day=max_trades_per_day,
        )
        position = None

        for ts, row in df.iterrows():
            current_date = ts.date()
            self.risk_engine.maybe_reset_day(current_date)

            if position is None:
                if not self.risk_engine.can_trade(current_date):
                    self.equity_curve.append(self.capital)
                    continue
                signals = strategy_fn(df.loc[:ts], symbol)
                if signals:
                    signal = signals[-1]
                    if not self.risk_engine.can_trade(current_date):
                        self.equity_curve.append(self.capital)
                        continue
                    qty = self.risk_engine.position_size(signal.entry, signal.stoploss, self.risk_pct)
                    if qty <= 0:
                        self.equity_curve.append(self.capital)
                        continue
                    position = {
                        'entry_ts': ts,
                        'side': signal.side,
                        'symbol': symbol,
                        'entry_price': signal.entry,
                        'qty': qty,
                        'stoploss': signal.stoploss,
                        'target': signal.targets[0],
                        'trailing_stop': signal.trailing_stop,
                    }
            else:
                if position['side'] == 'BUY':
                    if row['low'] <= position['stoploss']:
                        exit_price = position['stoploss']
                    elif row['high'] >= position['target']:
                        exit_price = position['target']
                    else:
                        exit_price = None
                else:
                    if row['high'] >= position['stoploss']:
                        exit_price = position['stoploss']
                    elif row['low'] <= position['target']:
                        exit_price = position['target']
                    else:
                        exit_price = None

                if exit_price is not None:
                    pnl = (
                        (exit_price - position['entry_price']) * position['qty']
                        if position['side'] == 'BUY'
                        else (position['entry_price'] - exit_price) * position['qty']
                    )
                    trade = BacktestTrade(
                        entry_ts=str(position['entry_ts']),
                        exit_ts=str(ts),
                        side=position['side'],
                        symbol=position['symbol'],
                        entry_price=position['entry_price'],
                        exit_price=exit_price,
                        qty=position['qty'],
                        pnl=round(pnl, 2),
                        return_pct=round(pnl / (position['entry_price'] * position['qty']) * 100, 2),
                        stoploss=position['stoploss'],
                        target=position['target'],
                    )
                    self.trades.append(trade)
                    self.capital += pnl
                    self.risk_engine.register_trade(pnl)
                    position = None
            self.equity_curve.append(self.capital)

        return {
            'initial_capital': self.initial_capital,
            'final_capital': round(self.capital, 2),
            'equity_curve': self.equity_curve,
            'trades': [asdict(t) for t in self.trades],
            'total_trades': len(self.trades),
            'win_rate': self._win_rate(),
            'max_drawdown': self._max_drawdown(),
        }

    def _win_rate(self) -> float:
        if not self.trades:
            return 0.0
        wins = sum(1 for t in self.trades if t.pnl > 0)
        return round(wins / len(self.trades) * 100, 2)

    def _max_drawdown(self) -> float:
        peak = self.initial_capital
        max_dd = 0.0
        for value in self.equity_curve:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak * 100
            max_dd = max(max_dd, drawdown)
        return round(max_dd, 2)
