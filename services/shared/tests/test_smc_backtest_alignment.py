import pandas as pd
import numpy as np
from typing import Any

from trading_shared.strategies.scalping_desk import smc_backtest as smc_bt
from trading_shared.strategies.scalping_desk.smc_scalping_engine import SMCSetup


def _make_linear_candles(start_ts: str, n: int, step_points: float) -> pd.DataFrame:
    ts = pd.date_range(start=start_ts, periods=n, freq="1min")
    close = 100.0 + step_points * np.arange(n, dtype=float)
    open_ = close - 0.25
    high = close + 0.25
    low = close - 0.5
    volume = np.full(n, 1000.0)
    return pd.DataFrame(
        {
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S").tolist(),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


def test_smc_backtest_sets_premium_brackets_for_exit(monkeypatch):
    """
    Regression for live/backtest divergence:
    Previously SMC backtest created active trades without `entry/target/stoploss`,
    so premium-based exits were modeled incorrectly.
    """

    candles = _make_linear_candles("2026-08-24 09:15:00", n=120, step_points=5.0)

    setup = SMCSetup(
        strategy_id="smc_orb_fvg",
        signal_type="CALL",
        bias="bullish",
        entry_zone=(0.0, 0.0),
        stop_pts=8.0,
        target_pts=10.0,
    )

    monkeypatch.setitem(
        smc_bt.SMC_EVALUATORS,
        "smc_orb_fvg",
        lambda mtf, params: setup,
    )

    # Make sizing deterministic: the returned `premium` is treated as entry premium.
    monkeypatch.setattr(smc_bt, "backtest_size_for_bar", lambda **_: (1, 100000.0, 10.0))

    captured: dict[str, float] = {}

    def _capture_should_exit(signal_type, current_ltp, entry, target, stoploss, indicators, *args, **kwargs):
        captured.setdefault("entry", float(entry or 0))
        captured.setdefault("target", float(target or 0))
        captured.setdefault("stoploss", float(stoploss or 0))
        return False, ""

    monkeypatch.setattr(smc_bt, "should_exit", _capture_should_exit)

    res = smc_bt.run_single_smc_backtest(
        candles,
        "smc_orb_fvg",
        lot_size=1,
        capital=100000.0,
        params={
            "smc_entry_scan_every": 1,
            "smc_min_bars_between": 1,
            "max_hold_bars": 6,
            "smc_max_bars": 200,
        },
        max_loss_per_day=1_000_000.0,
        max_trades_per_day=5,
    )

    assert res["total_trades"] >= 1
    # These must be non-zero after the fix (they were all 0 in the buggy version).
    assert captured["entry"] > 0
    assert captured["target"] > 0
    assert captured["stoploss"] > 0


def test_smc_backtest_respects_ai_daily_stop(monkeypatch):
    """
    Regression for live/backtest divergence:
    Live desk applies AI daily stop; SMC backtest must gate new entries after stop.
    """

    candles = _make_linear_candles("2026-08-24 09:15:00", n=120, step_points=1.0)

    setup = SMCSetup(
        strategy_id="smc_orb_fvg",
        signal_type="CALL",
        bias="bullish",
        entry_zone=(0.0, 0.0),
        stop_pts=100.0,   # avoid index stop
        target_pts=0.5,  # exit on next bar (move=1)
    )

    monkeypatch.setitem(
        smc_bt.SMC_EVALUATORS,
        "smc_orb_fvg",
        lambda mtf, params: setup,
    )
    monkeypatch.setattr(smc_bt, "backtest_size_for_bar", lambda **_: (1, 100000.0, 10.0))

    # Prevent premium-based exits; rely on should_exit_index for the quick exit.
    monkeypatch.setattr(smc_bt, "should_exit", lambda *args, **kwargs: (False, ""))

    # Force AI daily stop to trigger immediately after the first exit.
    def _force_stop(*_args, **_kwargs):
        return {"stop_trading": True}

    monkeypatch.setattr(smc_bt, "evaluate_ai_daily_stop", _force_stop)

    res = smc_bt.run_single_smc_backtest(
        candles,
        "smc_orb_fvg",
        lot_size=1,
        capital=100000.0,
        params={
            "smc_entry_scan_every": 1,
            "smc_min_bars_between": 1,
            "max_hold_bars": 6,
            "smc_max_bars": 200,
        },
        max_loss_per_day=1_000_000.0,
        max_trades_per_day=10,
    )

    # After the fix, AI daily stop should prevent further entries that day.
    assert res["total_trades"] == 1


def test_smc_desk_path_forces_scan_every_one():
    """Desk strategy backtest must not inherit optimizer scan throttle."""
    from trading_shared.strategies.scalping_desk import backtest as desk_bt

    captured: dict[str, Any] = {}

    def _capture_run(candles, strategy_id, lot_size, capital, **kwargs):
        captured["params"] = kwargs.get("params") or {}
        captured["ai_entry"] = kwargs.get("ai_entry")
        return {
            "status": "completed",
            "strategy_id": strategy_id,
            "total_trades": 0,
            "trades": [],
            "equity_curve": [],
            "initial_capital": capital,
            "final_capital": capital,
            "total_pnl": 0,
            "win_rate": 0,
            "max_drawdown": 0,
            "profit_factor": 0,
            "avg_profit_win": 0,
            "avg_loss_loss": 0,
            "avg_trade_pnl": 0,
            "avg_risk_reward": 0,
            "avg_trade_duration_bars": 0,
            "avg_hold_minutes": 0,
            "consistency_score": 0,
            "bars_processed": 0,
            "params": captured["params"],
        }

    import trading_shared.strategies.scalping_desk.smc_backtest as smc_mod

    candles = _make_linear_candles("2026-08-24 09:15:00", n=100, step_points=1.0)
    # Patch at call site used by run_strategy_backtest
    original = smc_mod.run_single_smc_backtest
    smc_mod.run_single_smc_backtest = _capture_run  # type: ignore[assignment]
    try:
        desk_bt.run_strategy_backtest(
            candles,
            "1m",
            lot_size=65,
            capital=29500,
            strategy_code="SCALP-SMC-003",
            instrument_key="nifty50",
            params={"smc_entry_scan_every": 2},
            ai_entry=True,
        )
    finally:
        smc_mod.run_single_smc_backtest = original  # type: ignore[assignment]

    assert captured["params"].get("smc_entry_scan_every") == 1
    assert captured["ai_entry"] is True

