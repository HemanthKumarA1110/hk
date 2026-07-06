import pytest

from trading_shared.broker.angel_one.exceptions import AngelOneAuthError
from trading_shared.execution.executor import OrderRejectedError
from trading_shared.execution.paper import PaperTradeExecutor, _calc_pnl, _desk_to_source, _source_label


class _FakeTickBus:
    def __init__(self, ltp: float | None):
        self.ltp = ltp

    def get_tick(self, _exchange_type, _token):
        if self.ltp is None:
            return None
        return {"ltp": self.ltp, "token": _token}


def test_calc_pnl_buy_and_sell():
    assert _calc_pnl("BUY", 100, 105, 10) == 50
    assert _calc_pnl("SELL", 100, 95, 10) == 50


def test_desk_to_source_mapping():
    assert _desk_to_source(None) == "live_trading"
    assert _desk_to_source("intraday") == "intraday_desk"
    assert _desk_to_source("swing") == "swing_desk"
    assert _desk_to_source("scalping:nifty50") == "scalping_desk"
    assert _source_label("intraday_desk") == "Intraday"
    assert _source_label("swing_desk") == "Swing"
    assert _source_label("scalping_desk") == "Scalping"


def test_infer_source_from_order_product():
    from trading_shared.execution.paper import _infer_source_from_order
    from trading_shared.models.order import BrokerOrder

    swing = BrokerOrder(exchange="NSE", product="DELIVERY", symbol="CIPLA-EQ")
    assert _infer_source_from_order(swing, None) == "swing_desk"
    intraday = BrokerOrder(exchange="NSE", product="INTRADAY", symbol="SBIN-EQ")
    assert _infer_source_from_order(intraday, None) == "intraday_desk"
    scalp = BrokerOrder(exchange="NFO", product="INTRADAY", symbol="NIFTY07JUL2624400CE")
    assert _infer_source_from_order(scalp, None) == "scalping_desk"


@pytest.mark.asyncio
async def test_resolve_live_price_uses_redis_stream(monkeypatch):
    executor = PaperTradeExecutor.__new__(PaperTradeExecutor)
    executor.market_bus = _FakeTickBus(142.5)
    price, source = await PaperTradeExecutor._resolve_live_price(executor, "NFO", "NIFTY24JUL24000CE", "12345", 0)
    assert price == 142.5
    assert source == "angel_stream"


@pytest.mark.asyncio
async def test_resolve_live_price_rejects_without_live_data():
    executor = PaperTradeExecutor.__new__(PaperTradeExecutor)
    executor.market_bus = _FakeTickBus(None)

    class _FakeSession:
        async def get_client_for_user(self, _user_id):
            raise AngelOneAuthError("no session")

    executor.session_manager = _FakeSession()

    with pytest.raises(OrderRejectedError):
        await PaperTradeExecutor._resolve_live_price(executor, "NSE", "SBIN-EQ", "999", 0)
