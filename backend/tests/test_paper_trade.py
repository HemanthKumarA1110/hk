from app.services.paper_trade import PaperTradeService


def test_place_order_adds_order_and_position():
    service = PaperTradeService()
    order = service.place_order('NSE:RELIANCE', 'BUY', 1, 100.0, mode='paper', order_type='market')

    assert order.status == 'filled'
    assert order.symbol == 'NSE:RELIANCE'
    assert len(service.orders) == 1
    assert len(service.positions) == 1

    position = service.positions[0]
    assert position.symbol == 'NSE:RELIANCE'
    assert position.status == 'open'
    assert position.entry_price == 100.0
