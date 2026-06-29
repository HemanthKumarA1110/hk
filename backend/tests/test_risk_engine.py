from datetime import date

from app.services.risk_engine import RiskEngine


def test_initial_can_trade():
    engine = RiskEngine(equity=100000.0)
    assert engine.can_trade(date(2026, 1, 1)) is True


def test_position_size_calculation():
    engine = RiskEngine(equity=100000.0)
    size = engine.position_size(entry=100.0, stoploss=95.0, risk_pct=1.0)
    assert size == 200


def test_invalid_position_size_returns_zero():
    engine = RiskEngine(equity=100000.0)
    assert engine.position_size(entry=100.0, stoploss=100.0, risk_pct=1.0) == 0


def test_daily_loss_blocks_trading():
    engine = RiskEngine(equity=100000.0)
    engine.set_limits(max_daily_loss_pct=1.0)
    engine.register_trade(-1500.0)
    assert engine.can_trade(date(2026, 1, 1)) is False


def test_max_trades_blocks_trading():
    engine = RiskEngine(equity=100000.0)
    engine.set_limits(max_trades_per_day=1)
    engine.trade_count = 1
    assert engine.can_trade(date(2026, 1, 1)) is False
