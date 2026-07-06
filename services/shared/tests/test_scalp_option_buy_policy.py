from trading_shared.strategies.scalping_desk.capital_utilization import backtest_option_trade_pnl
from trading_shared.strategies.scalping_desk.constants import (
    validate_option_buy_contract,
)
from trading_shared.strategies.scalping_desk.engine import estimate_option_mark_premium
from trading_shared.strategies.scalping_desk.option_execution import ensure_buy_only_signal


def test_validate_option_buy_contract():
    assert validate_option_buy_contract("NIFTY07JUL2624400CE", "CALL")
    assert validate_option_buy_contract("NIFTY07JUL2624400PE", "PUT")
    assert not validate_option_buy_contract("NIFTY07JUL2624400PE", "CALL")
    assert not validate_option_buy_contract("NIFTY28JUL26FUT", "CALL")


def test_backtest_option_trade_pnl_long_only():
    pnl = backtest_option_trade_pnl(58.0, 84.0, lot_size=25, lots=2)
    assert pnl == (84.0 - 58.0) * 25 * 2


def test_ensure_buy_only_signal():
    sig = ensure_buy_only_signal(
        {
            "signal_type": "CALL",
            "option_symbol": "NIFTY07JUL2624400CE",
            "entry": 58.0,
            "target": 66.0,
            "stoploss": 52.0,
        }
    )
    assert sig["order_side"] == "BUY"
    assert sig["execution_policy"] == "buy_only"
