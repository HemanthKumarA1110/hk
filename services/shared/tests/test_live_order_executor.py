from unittest.mock import AsyncMock, MagicMock

import pytest

from trading_shared.execution.executor import OrderExecutor, OrderRejectedError
from trading_shared.schemas.order import OrderCreateRequest


@pytest.mark.asyncio
async def test_closing_order_bypasses_allocation_gate_and_releases_exposure(monkeypatch):
    executor = OrderExecutor.__new__(OrderExecutor)
    executor.user_id = 1
    executor.db = MagicMock()
    executor.db.add = MagicMock()
    executor.db.commit = MagicMock()
    executor.db.refresh = MagicMock(side_effect=lambda row: row)
    executor.risk = MagicMock()
    executor.risk.engine.can_trade = MagicMock(return_value=(False, "Max capital allocation reached"))
    executor.risk.engine.dynamic_stoploss = MagicMock(return_value=72.0)
    executor.risk.register_trade = MagicMock()
    executor.session_manager = MagicMock()
    executor.session_manager.get_client_for_user = AsyncMock(
        return_value=MagicMock(
            place_order=AsyncMock(return_value={"message": "SUCCESS", "data": {"orderid": "OID-1"}})
        )
    )

    async def _resolve_symbol(*_args, **_kwargs):
        return "NIFTY18AUG2624200PE", "12345", "NFO"

    async def _poll_order_rejection(*_args, **_kwargs):
        return None

    monkeypatch.setattr(executor, "_resolve_symbol", _resolve_symbol)
    monkeypatch.setattr(executor, "_poll_order_rejection", _poll_order_rejection)

    payload = OrderCreateRequest(
        symbol="NIFTY18AUG2624200PE",
        symboltoken="12345",
        exchange="NFO",
        side="SELL",
        qty=585,
        order_type="MARKET",
        price=100.0,
        product="INTRADAY",
    )

    result = await executor.place_order(
        payload,
        desk="scalping:nifty50",
        lot_size=65,
        is_closing_order=True,
    )

    assert result["qty"] == 585
    executor.risk.engine.can_trade.assert_not_called()
    executor.risk.register_trade.assert_called_once_with(0.0, -58500.0)


@pytest.mark.asyncio
async def test_entry_order_still_honors_allocation_gate(monkeypatch):
    executor = OrderExecutor.__new__(OrderExecutor)
    executor.user_id = 1
    executor.db = MagicMock()
    executor.db.add = MagicMock()
    executor.db.commit = MagicMock()
    executor.db.refresh = MagicMock(side_effect=lambda row: row)
    executor.risk = MagicMock()
    executor.risk.engine.can_trade = MagicMock(return_value=(False, "Max capital allocation reached"))
    executor.risk.engine.dynamic_stoploss = MagicMock(return_value=72.0)
    executor.risk.register_trade = MagicMock()
    executor.session_manager = MagicMock()
    executor.session_manager.get_client_for_user = AsyncMock(return_value=MagicMock())

    async def _resolve_symbol(*_args, **_kwargs):
        return "NIFTY18AUG2624200PE", "12345", "NFO"

    monkeypatch.setattr(executor, "_resolve_symbol", _resolve_symbol)

    payload = OrderCreateRequest(
        symbol="NIFTY18AUG2624200PE",
        symboltoken="12345",
        exchange="NFO",
        side="BUY",
        qty=585,
        order_type="MARKET",
        price=100.0,
        product="INTRADAY",
    )

    with pytest.raises(OrderRejectedError, match="Max capital allocation reached"):
        await executor.place_order(
            payload,
            desk="scalping:nifty50",
            lot_size=65,
        )

    executor.risk.engine.can_trade.assert_called_once()
    executor.risk.register_trade.assert_not_called()
