from sqlmodel import SQLModel, create_engine, select, Session

import app.services.broker_service as broker_module
from app.models import Trade


def test_execute_order_stores_trade(monkeypatch):
    engine = create_engine('sqlite:///:memory:', echo=False)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(broker_module, 'engine', engine)
    monkeypatch.setattr(
        broker_module.broker_service.client,
        'place_order_sync',
        lambda payload: {'status': 'filled', 'order_id': 'TEST123'},
    )

    result = broker_module.broker_service.execute_order(
        symbol='NSE:RELIANCE',
        side='BUY',
        qty=1,
        price=100.0,
        order_type='market',
    )

    assert result['status'] == 'filled'
    assert result['order_id'] == 'TEST123'

    with Session(engine) as session:
        trades = session.exec(select(Trade)).all()
    assert len(trades) == 1
    assert trades[0].order_id == 'TEST123'
    assert trades[0].symbol == 'NSE:RELIANCE'


def test_broker_status_and_quote(monkeypatch):
    monkeypatch.setattr(
        broker_module.broker_service.client,
        'get_account_status_sync',
        lambda: {
            'connected': True,
            'user_id': 'user_1',
            'client_id': 'client_1',
            'session_token': True,
            'refresh_token': True,
            'base_url': 'https://api.angelone.in',
        },
    )
    monkeypatch.setattr(
        broker_module.broker_service.client,
        'get_live_quote_sync',
        lambda symbol: {'last_price': 123.45, 'bid': 123.0, 'ask': 123.9, 'volume': 1000},
    )

    status = broker_module.broker_service.get_broker_status()
    assert status['connected'] is True
    assert status['user_id'] == 'user_1'

    quote = broker_module.broker_service.get_live_quote('NSE:RELIANCE')
    assert quote['last_price'] == 123.45
    assert quote['volume'] == 1000
