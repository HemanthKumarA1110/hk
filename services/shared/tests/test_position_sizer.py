from trading_shared.strategies.scalping_desk.position_sizer import compute_dynamic_position_size


def test_halt_on_trade_limit():
    out = compute_dynamic_position_size(
        instrument_key="nifty50",
        capital=100_000,
        open_pnl=0,
        trade_count=3,
        consecutive_losses=0,
        entry=120,
        stop_loss=110,
        config={"max_trades_per_day": 3},
        risk_pts=7,
    )
    assert out["action"] == "HALT"
    assert out["reason"] == "daily trade limit reached"


def test_halt_on_daily_loss():
    out = compute_dynamic_position_size(
        instrument_key="nifty50",
        capital=100_000,
        open_pnl=-5001,
        trade_count=1,
        consecutive_losses=0,
        entry=120,
        stop_loss=110,
        config={"max_daily_loss_pct": 5.0},
        risk_pts=7,
    )
    assert out["action"] == "HALT"
    assert "daily loss" in out["reason"]


def test_half_size_after_two_losses():
    out = compute_dynamic_position_size(
        instrument_key="nifty50",
        capital=100_000,
        open_pnl=0,
        trade_count=1,
        consecutive_losses=2,
        entry=120,
        stop_loss=113,
        config={"risk_per_trade_pct": 2.0, "max_lots_per_trade": 2},
        risk_pts=7,
    )
    assert out["action"] == "TRADE"
    assert out["lots"] == 1
    assert "consecutive losses" in out["reason"]


def test_max_two_lots():
    out = compute_dynamic_position_size(
        instrument_key="nifty50",
        capital=1_000_000,
        open_pnl=0,
        trade_count=0,
        consecutive_losses=0,
        entry=120,
        stop_loss=113,
        config={"risk_per_trade_pct": 5.0, "max_lots_per_trade": 2},
        risk_pts=7,
    )
    assert out["action"] == "TRADE"
    assert out["lots"] <= 2
