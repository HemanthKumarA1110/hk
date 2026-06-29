from trading_shared.execution.auto_trading import compute_auto_trade_qty


def test_compute_qty_from_max_amount():
    qty, notional = compute_auto_trade_qty(entry=800, max_order_amount=10000, recommended_size_pct=100, risk_qty=50)
    assert qty == 12
    assert notional == 9600


def test_compute_qty_scales_with_ai_size_pct():
    qty, _ = compute_auto_trade_qty(entry=100, max_order_amount=10000, recommended_size_pct=50, risk_qty=200)
    assert qty == 50


def test_compute_qty_capped_by_risk():
    qty, _ = compute_auto_trade_qty(entry=100, max_order_amount=100000, recommended_size_pct=100, risk_qty=5)
    assert qty == 5


def test_compute_qty_too_small_amount():
    qty, notional = compute_auto_trade_qty(entry=5000, max_order_amount=1000, recommended_size_pct=100, risk_qty=10)
    assert qty == 0
    assert notional == 0
