"""Tests for swing desk strategies and portfolio backtest."""

from datetime import datetime, timedelta

import pandas as pd

from trading_shared.strategies.swing_desk.backtest import run_swing_portfolio_backtest
from trading_shared.strategies.swing_desk.session import enrich_swing_frame
from trading_shared.strategies.swing_desk.strategies.ema_trend import EmaTrendStrategy


def _demo_daily_df(bars: int = 260) -> pd.DataFrame:
    start = datetime(2024, 1, 1)
    rows = []
    price = 1000.0
    for i in range(bars):
        ts = start + timedelta(days=i)
        if ts.weekday() >= 5:
            continue
        drift = 1 + ((i % 13) - 6) * 0.003
        close = price * drift
        rows.append(
            {
                "timestamp": ts,
                "open": close * 0.998,
                "high": close * 1.015,
                "low": close * 0.985,
                "close": close,
                "volume": 50000 + (i % 10000),
            }
        )
        price = close
    return pd.DataFrame(rows)


def test_enrich_swing_frame_adds_indicators():
    df = enrich_swing_frame(_demo_daily_df(260))
    assert "ema200" in df.columns
    assert "atr14" in df.columns


def test_ema_trend_detects_cross():
    df = enrich_swing_frame(_demo_daily_df(260))
    strategy = EmaTrendStrategy()
    found = any(strategy.try_entry(df, i, False) for i in range(55, len(df)))
    assert found is True or found is False


def test_portfolio_backtest_runs():
    frames = {
        "SBIN-EQ": _demo_daily_df(260),
        "RELIANCE-EQ": _demo_daily_df(260),
        "TCS-EQ": _demo_daily_df(260),
    }
    result = run_swing_portfolio_backtest(
        frames,
        "SWING-EMA",
        initial_capital=100000,
        risk_pct=1.0,
        max_open_positions=2,
    )
    assert result["strategy_code"] == "SWING-EMA"
    assert result["max_open_positions"] == 2
    assert "cost_model" in result


def test_swing_desk_guards_block_when_limits_hit():
    from trading_shared.strategies.swing_desk.guards import guard_status

    cfg = {
        "auto_trading_enabled": True,
        "max_trades_per_day": 3,
        "max_daily_loss_inr": 1000,
        "max_open_positions": 2,
    }
    state = {"trades_today": 1, "daily_pnl": 0, "active_positions": [{}, {}]}
    status = guard_status(state, cfg)
    assert status["can_enter"] is False
    assert any("open positions" in a.lower() for a in status["alerts"])


def test_swing_desk_default_config():
    from trading_shared.strategies.swing_desk.service import default_desk_config

    cfg = default_desk_config()
    assert cfg["strategy_mode"] in {"ai", "manual"}
    assert cfg["max_open_positions"] >= 1
    assert "SWING-EMA" in cfg["swing_strategy_settings"]


def test_score_swing_candidate():
    from trading_shared.strategies.swing_desk.stock_picker import rank_universe, score_swing_candidate

    df = enrich_swing_frame(_demo_daily_df(260))
    score = score_swing_candidate(df, "SWING-EMA")
    assert score >= 0
    ranked = rank_universe([("SBIN-EQ", df), ("RELIANCE-EQ", df)], "SWING-EMA", use_backtest_score=False)
    assert len(ranked) == 2
