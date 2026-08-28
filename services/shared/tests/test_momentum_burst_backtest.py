"""Momentum Burst backtest should produce trades on index OHLCV."""

import pandas as pd

from trading_shared.backtest.data_loader import BacktestDataLoader
from trading_shared.strategies.scalping_desk.backtest import run_strategy_backtest
from trading_shared.strategies.scalping_desk.engine import enrich_candles
from trading_shared.strategies.scalping_desk.strategies import evaluate_momentum_burst


class _FakeDb:
    pass


def test_momentum_burst_fires_on_zero_volume_index_proxy():
    loader = BacktestDataLoader(_FakeDb())
    df = loader._generate_demo("NIFTY", "1m", "2026-05-05", "2026-05-20")
    data = enrich_candles(df.reset_index(drop=True))
    assert bool(data["volume_proxy"].iloc[-1]) is True

    signals = 0
    for i in range(30, len(data)):
        seg = data.iloc[max(0, i + 1 - 60) : i + 1]
        if evaluate_momentum_burst(seg, "1m", {"rows": []}, 25, enriched=True, skip_session=True):
            signals += 1
    assert signals > 0


def test_scalp_ad_005_backtest_returns_capital_on_empty_trades():
    loader = BacktestDataLoader(_FakeDb())
    df = loader._generate_demo("BANKNIFTY", "1m", "2026-05-05", "2026-07-04")
    result = run_strategy_backtest(
        df,
        "1m",
        15,
        100_000,
        strategy_code="SCALP-AD-005",
        instrument_key="banknifty",
    )
    assert result["initial_capital"] == 100_000
    assert result["final_capital"] == result["initial_capital"] or result["total_trades"] > 0
    if result["total_trades"] == 0:
        assert result.get("message")
        assert result["avg_profit_win"] == 0
    else:
        assert result["total_trades"] > 0
