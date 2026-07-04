"""Tests for modular intraday desk strategies and backtest."""

import pandas as pd

from trading_shared.strategies.intraday_desk.backtest import run_intraday_strategy_backtest
from trading_shared.strategies.intraday_desk.session import enrich_intraday_frame
from trading_shared.strategies.intraday_desk.strategies.orb import OpeningRangeBreakout


def _demo_intraday_df(days: int = 5) -> pd.DataFrame:
    from datetime import datetime, timedelta

    rows = []
    start = datetime(2025, 1, 6)
    for d in range(days):
        day = start + timedelta(days=d)
        if day.weekday() >= 5:
            continue
        t = day.replace(hour=9, minute=15)
        price = 800.0
        for i in range(75):
            drift = 1 + ((i % 9) - 4) * 0.002
            close = price * drift
            high = close * 1.003
            low = close * 0.997
            if i < 6:
                high = close * 1.001
                low = close * 0.999
            if i == 7:
                high = close * 1.02
                close = close * 1.015
            rows.append(
                {
                    "timestamp": t,
                    "open": close * 0.999,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": 15000 if i != 7 else 40000,
                }
            )
            price = close
            t += timedelta(minutes=5)
    return pd.DataFrame(rows)


def test_enrich_handles_mixed_iso_timestamps():
    df = pd.DataFrame(
        [
            {"timestamp": "2026-07-04 09:20:00", "open": 800, "high": 801, "low": 799, "close": 800.5, "volume": 10000},
            {"timestamp": "2026-07-04T09:49:22.829195+00:00", "open": 800.5, "high": 802, "low": 800, "close": 801, "volume": 12000},
        ]
    )
    enriched = enrich_intraday_frame(df)
    assert enriched["timestamp"].notna().all()
    assert "vwap" in enriched.columns
    df = enrich_intraday_frame(_demo_intraday_df(2))
    assert "or_high" in df.columns
    assert "vwap" in df.columns
    assert df["or_high"].notna().any()


def test_orb_detects_breakout():
    df = enrich_intraday_frame(_demo_intraday_df(3))
    strategy = OpeningRangeBreakout()
    signal = None
    for i in range(25, len(df)):
        signal = strategy.try_entry(df, i, traded_today=False)
        if signal:
            break
    assert signal is not None
    assert signal.side == "BUY"


def test_intraday_backtest_runs_for_each_strategy():
    df = _demo_intraday_df(8)
    for code in ("INTRA-ORB", "INTRA-VWAP", "INTRA-EMA-RSI"):
        result = run_intraday_strategy_backtest(df, code, "SBIN-EQ", initial_capital=100000)
        assert result["strategy_code"] == code
        assert "total_trades" in result
        assert result["cost_model"]


def test_universe_backtest_auto_picks_and_aggregates():
    from trading_shared.strategies.intraday_desk.backtest import run_intraday_universe_backtest

    class _Loader:
        def resolve_token(self, symbol, token=None):
            return "1", symbol

        def load(self, **kwargs):
            return _demo_intraday_df(8), "demo"

    result = run_intraday_universe_backtest(
        _Loader(),
        user_id=1,
        strategy_code="INTRA-ORB",
        exchange="NSE",
        interval="5m",
        from_date="2025-01-01",
        to_date="2025-03-01",
        use_demo_data=True,
        initial_capital=100000,
        risk_pct=1.0,
        top_n=3,
        universe=["SBIN-EQ", "RELIANCE-EQ", "TCS-EQ"],
    )
    assert result["selection_mode"] == "auto"
    assert len(result["picked_stocks"]) <= 3
    assert result["universe_screened"] == 3


def test_intraday_desk_guards_block_when_limits_hit():
    from trading_shared.strategies.intraday_desk.guards import guard_status

    cfg = {"auto_trading_enabled": True, "max_trades_per_day": 3, "max_daily_loss_inr": 1000}
    state = {"trades_today": 3, "daily_pnl": -500}
    status = guard_status(state, cfg)
    assert status["can_enter"] is False
    assert any("Max trades" in a for a in status["alerts"])

    state2 = {"trades_today": 1, "daily_pnl": -1500}
    status2 = guard_status(state2, cfg)
    assert status2["can_enter"] is False
    assert any("max loss" in a.lower() for a in status2["alerts"])


def test_intraday_desk_default_config():
    from trading_shared.strategies.intraday_desk.service import default_desk_config

    cfg = default_desk_config()
    assert cfg["strategy_mode"] in {"ai", "manual"}
    assert cfg["capital"] > 0
    assert "INTRA-ORB" in cfg["intraday_strategy_settings"]
