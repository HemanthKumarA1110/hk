import pytest

from trading_shared.broker.angel_one.exceptions import AngelOneAuthError
from trading_shared.execution.executor import OrderRejectedError
from trading_shared.execution.paper import PaperTradeExecutor, _calc_pnl, _desk_to_source, _source_label
from trading_shared.schemas.order import OrderCreateRequest
from trading_shared.strategies.scalping_desk.service import _entry_bars_held


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


def test_entry_bars_held_uses_entry_time():
    from datetime import datetime, timedelta, timezone

    ten_min_ago = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    held = _entry_bars_held({"entry_time": ten_min_ago})
    assert held >= 9


@pytest.mark.asyncio
async def test_place_order_does_not_persist_risk_rejection(monkeypatch):
    from unittest.mock import MagicMock

    executor = PaperTradeExecutor.__new__(PaperTradeExecutor)
    executor.user_id = 1
    executor.db = MagicMock()
    executor.risk = MagicMock()
    executor.risk.evaluate_trade.return_value = {"approved": False, "reason": "Daily loss cap"}
    executor.risk.engine.dynamic_stoploss.return_value = 90.0

    async def _resolve_symbol(*_args, **_kwargs):
        return "NIFTY24JUL24000CE", "12345", "NFO"

    async def _resolve_live_price(*_args, **_kwargs):
        return 142.5, "angel_stream"

    monkeypatch.setattr(executor, "_resolve_symbol", _resolve_symbol)
    monkeypatch.setattr(executor, "_resolve_live_price", _resolve_live_price)

    payload = OrderCreateRequest(
        symbol="NIFTY24JUL24000CE",
        symboltoken="12345",
        exchange="NFO",
        side="BUY",
        qty=50,
        order_type="MARKET",
        price=0,
        product="INTRADAY",
    )

    with pytest.raises(OrderRejectedError, match="Daily loss cap"):
        await executor.place_order(payload)

    executor.db.add.assert_not_called()
    executor.db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_desk_paper_order_uses_desk_qty_despite_full_exposure(monkeypatch):
    from unittest.mock import MagicMock

    executor = PaperTradeExecutor.__new__(PaperTradeExecutor)
    executor.user_id = 1
    executor.db = MagicMock()
    executor.db.add = MagicMock()
    executor.db.commit = MagicMock()
    executor.db.refresh = MagicMock(side_effect=lambda row: row)
    executor.risk = MagicMock()
    executor.risk.engine.can_trade.return_value = (True, "ok")
    executor.risk.engine.dynamic_stoploss.return_value = 72.0
    executor.risk.register_trade = MagicMock(return_value={})

    async def _resolve_symbol(*_args, **_kwargs):
        return "NIFTY14JUL2624200CE", "12345", "NFO"

    async def _resolve_live_price(*_args, **_kwargs):
        return 82.2, "limit"

    monkeypatch.setattr(executor, "_resolve_symbol", _resolve_symbol)
    monkeypatch.setattr(executor, "_resolve_live_price", _resolve_live_price)

    payload = OrderCreateRequest(
        symbol="NIFTY14JUL2624200CE",
        symboltoken="12345",
        exchange="NFO",
        side="BUY",
        qty=75,
        order_type="MARKET",
        price=82.2,
        product="INTRADAY",
    )

    result = await executor.place_order(payload, desk="scalping:nifty50", strategy_code="SCALP-BT-003")

    assert result["qty"] == 75
    executor.risk.evaluate_trade.assert_not_called()
