#!/usr/bin/env python3
"""Quick intraday + swing AI vs baseline comparison."""
from datetime import date, timedelta
from trading_shared.db.session import SessionLocal
from trading_shared.backtest.data_loader import BacktestDataLoader
from trading_shared.strategies.intraday_desk.backtest import run_intraday_universe_backtest
from trading_shared.strategies.swing_desk.backtest import run_swing_universe_backtest

user_id = 1
days = 60
capital = 100000
top_n = 15
to_date = date.today()
from_date = to_date - timedelta(days=days)
db = SessionLocal()
loader = BacktestDataLoader(db)
print("INTRADAY + SWING · baseline vs AI (entry score>=40, dynamic exit)")
print("-" * 90)
for code in ("INTRA-ORB", "INTRA-VWAP-ORB"):
    b = run_intraday_universe_backtest(
        loader, user_id=user_id, strategy_code=code, exchange="NSE", interval="5m",
        from_date=from_date.isoformat(), to_date=to_date.isoformat(), use_demo_data=False,
        initial_capital=capital, risk_pct=1.0, top_n=top_n,
    )
    a = run_intraday_universe_backtest(
        loader, user_id=user_id, strategy_code=code, exchange="NSE", interval="5m",
        from_date=from_date.isoformat(), to_date=to_date.isoformat(), use_demo_data=False,
        initial_capital=capital, risk_pct=1.0, top_n=top_n, ai_entry=True, ai_exit=True,
    )
    dw = a["win_rate"] - b["win_rate"]
    print(
        f"  {code:14} base {b['win_rate']:>5.1f}% ({b['total_trades']:>2} tr) ₹{b['total_pnl']:>8,.0f} | "
        f"AI {a['win_rate']:>5.1f}% ({a['total_trades']:>2} tr) ₹{a['total_pnl']:>8,.0f} Δwin {dw:+.1f}pp"
    )
for code in ("SWING-EMA", "SWING-RSI", "SWING-BO-ATR"):
    b = run_swing_universe_backtest(
        loader, user_id=user_id, strategy_code=code, exchange="NSE", interval="1d",
        from_date=from_date.isoformat(), to_date=to_date.isoformat(), use_demo_data=False,
        initial_capital=capital, risk_pct=1.0, max_open_positions=5, top_n=top_n, evaluation_days=days,
    )
    a = run_swing_universe_backtest(
        loader, user_id=user_id, strategy_code=code, exchange="NSE", interval="1d",
        from_date=from_date.isoformat(), to_date=to_date.isoformat(), use_demo_data=False,
        initial_capital=capital, risk_pct=1.0, max_open_positions=5, top_n=top_n, evaluation_days=days,
        ai_entry=True, ai_exit=True,
    )
    dw = a["win_rate"] - b["win_rate"]
    print(
        f"  {code:14} base {b['win_rate']:>5.1f}% ({b['total_trades']:>2} tr) ₹{b['total_pnl']:>8,.0f} | "
        f"AI {a['win_rate']:>5.1f}% ({a['total_trades']:>2} tr) ₹{a['total_pnl']:>8,.0f} Δwin {dw:+.1f}pp"
    )
db.close()
