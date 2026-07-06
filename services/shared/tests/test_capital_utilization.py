from trading_shared.strategies.scalping_desk.capital_utilization import (
    backtest_index_trade_pnl,
    compute_utilization_lots,
    ensure_session_capital,
    is_index_scalp_desk,
)


def test_index_scalp_keys():
    assert is_index_scalp_desk("nifty50")
    assert is_index_scalp_desk("banknifty")
    assert not is_index_scalp_desk("reliance")


def test_session_capital_t_plus_one_profits():
    state = {"trading_day": "2026-06-29", "daily_pnl": 2500}
    config = {"capital": 100_000, "auto_capital_from_broker": False, "capital_utilization_pct": 1.0}
    state, info = ensure_session_capital(state, config)
    assert info["session_start_capital"] == 100_000
    assert info["deployable_capital"] == 100_000


def test_session_capital_loss_reduces_deployable():
    state = {
        "trading_day": "2026-06-29",
        "session_start_capital": 100_000,
        "session_capital_source": "manual",
        "daily_pnl": -2000,
    }
    config = {"capital": 100_000, "capital_utilization_pct": 1.0}
    _, info = ensure_session_capital(state, config)
    assert info["deployable_capital"] == 98_000


def test_utilization_lots_full_capital():
    out = compute_utilization_lots(
        "nifty50",
        100_000,
        120,
        config={"max_trades_per_day": 3},
        state={"trades_today": 0, "session_start_capital": 100_000},
    )
    assert out["action"] == "TRADE"
    assert out["lots"] == 33  # 100000 / (120 * 25)


def test_utilization_halt_on_open_trade():
    out = compute_utilization_lots(
        "nifty50",
        100_000,
        120,
        config={"max_trades_per_day": 3},
        state={"active_trades": [{"status": "open"}], "trades_today": 1},
    )
    assert out["action"] == "HALT"
    assert "open trade" in out["reason"]


def test_broker_cash_seeds_session():
    state = {"trading_day": "2026-06-29"}
    config = {"capital": 50_000, "auto_capital_from_broker": True, "capital_utilization_pct": 0.95}
    state, info = ensure_session_capital(state, config, broker_cash=120_000)
    assert info["session_start_capital"] == 120_000
    assert info["session_capital_source"] == "broker"
    assert info["deployable_capital"] == 114_000


def test_backtest_pnl_scales_with_lots():
    one = backtest_index_trade_pnl("CALL", 24_000, 24_010, 25, 1)
    two = backtest_index_trade_pnl("CALL", 24_000, 24_010, 25, 2)
    assert one == 250
    assert two == one * 2


def test_backtest_size_compounds_with_equity():
    from trading_shared.strategies.scalping_desk.capital_utilization import backtest_size_for_bar

    base_lots, _, _ = backtest_size_for_bar(
        initial_capital=100_000,
        instrument_key="banknifty",
        spot=55_000,
        day="2026-06-01",
        day_pnl={},
        utilization_pct=0.95,
        max_lots=0,
        current_equity=100_000,
    )
    higher_lots, deploy_high, _ = backtest_size_for_bar(
        initial_capital=100_000,
        instrument_key="banknifty",
        spot=55_000,
        day="2026-06-01",
        day_pnl={},
        utilization_pct=0.95,
        max_lots=0,
        current_equity=150_000,
    )
    lower_lots, deploy_low, _ = backtest_size_for_bar(
        initial_capital=100_000,
        instrument_key="banknifty",
        spot=55_000,
        day="2026-06-01",
        day_pnl={},
        utilization_pct=0.95,
        max_lots=0,
        current_equity=50_000,
    )
    assert base_lots >= 1
    assert higher_lots >= base_lots
    assert lower_lots <= base_lots
    assert deploy_high > deploy_low
