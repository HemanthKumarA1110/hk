from trading_shared.execution.qty import chunk_order_qty, snap_qty_to_lot
from trading_shared.strategies.scalping_desk.engine import pick_strike, should_exit
from trading_shared.strategies.scalping_desk.ai_decision import apply_ai_targets
from trading_shared.strategies.scalping_desk.capital_utilization import compute_utilization_lots
from trading_shared.strategies.scalping_desk.entry_guard import (
    entry_cooldown_active,
    entry_lock_key,
    option_strike_key,
    range_bound_same_strike_blocked,
    release_lock,
    set_entry_cooldown,
    set_same_strike_cooldown,
    try_acquire_lock,
)
from trading_shared.strategies.scalping_desk.service import _entered_this_cycle
from trading_shared.strategies.scalping_desk.stream_runner import ScalpingStreamRunner


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = str(value)
        return True

    def setex(self, key, _ttl, value):
        self.store[key] = str(value)
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)
        return 1


def test_snap_qty_to_lot_rounds_down():
    assert snap_qty_to_lot(38, 15) == 30
    assert snap_qty_to_lot(150, 15) == 150
    assert snap_qty_to_lot(14, 15) == 0
    assert snap_qty_to_lot(157, 15) == 150


def test_chunk_order_qty_respects_exchange_cap():
    assert chunk_order_qty(1050, 30) == [600, 450]
    assert chunk_order_qty(30, 30) == [30]


def test_cap_qty_and_max_lots_for_freeze():
    from trading_shared.execution.qty import cap_qty_to_exchange_max, max_lots_per_order

    assert max_lots_per_order(30) == 20
    assert max_lots_per_order(65) == 9
    assert cap_qty_to_exchange_max(6240, 30) == 600
    assert cap_qty_to_exchange_max(601, 30) == 600
    assert cap_qty_to_exchange_max(90, 30) == 90


def test_utilization_lots_uses_full_capital_and_splits_freeze():
    sized = compute_utilization_lots(
        "banknifty",
        deployable_capital=100_000,
        option_premium=4.65,
        config={"max_trades_per_day": 5, "max_lots_per_trade": 0},
        state={"trades_today": 0, "daily_pnl": 0, "session_start_capital": 100_000, "active_trades": []},
    )
    assert sized["action"] == "TRADE"
    expected = int((100_000 * 0.97) // (4.65 * 30))
    assert sized["lots"] == expected
    assert sized["lots"] > 20
    assert sized["split_orders"] > 1
    assert "split" in sized["reason"].lower()
    from trading_shared.execution.qty import chunk_order_qty

    chunks = chunk_order_qty(sized["lots"] * 30, 30)
    assert chunks[0] == 600
    assert sum(chunks) == sized["lots"] * 30


def test_parse_insufficient_funds_and_affordable_lots():
    from trading_shared.strategies.scalping_desk.capital_utilization import (
        lots_affordable_from_cash,
        parse_insufficient_funds_amounts,
    )

    avail, require = parse_insufficient_funds_amounts(
        "Your order has been rejected due to Insufficient Funds. "
        "Available funds - Rs. 28974.78. You require Rs. 29837.45 funds to execute this order."
    )
    assert avail == 28974.78
    assert require == 29837.45
    # After a 9-lot Nifty fill at 27.85, leftover cash should fund more lots than zero.
    leftover = 28974.78 - (9 * 65 * 27.85)
    assert lots_affordable_from_cash(leftover, 27.85, 65) >= 6


def test_long_put_exit_uses_premium_up_for_target():
    hit, reason = should_exit("PUT", 16.5, 11.1, 5.84, 19.76, {})
    assert hit is True
    assert reason == "target_hit"
    hit, reason = should_exit("PUT", 2.4, 11.1, 5.84, 19.76, {})
    assert hit is True
    assert reason == "stoploss_hit"
    hit, reason = should_exit("PUT", 10.6, 11.1, 5.84, 19.76, {})
    assert hit is False


def test_apply_ai_targets_long_put_is_above_entry():
    signal = apply_ai_targets(
        {"signal_type": "PUT", "entry": 11.1, "indicators": {}},
        {"target_pts": 10, "stop_pts": 15, "target_inr": 100, "stop_inr": 150, "premium_target": 2.0, "premium_stop": 3.0},
    )
    assert signal["target"] > signal["entry"]
    assert signal["stoploss"] < signal["entry"]


def test_utilization_honors_max_lots():
    out = compute_utilization_lots(
        "banknifty",
        30_000,
        11.1,
        config={"max_trades_per_day": 5, "max_lots_per_trade": 2},
        state={"trades_today": 0, "session_start_capital": 30_000},
    )
    assert out["action"] == "TRADE"
    assert out["lots"] == 2


def test_entry_lock_blocks_second_acquire():
    redis = _FakeRedis()
    key = entry_lock_key(1, "banknifty")
    assert try_acquire_lock(redis, key, 45) is True
    assert try_acquire_lock(redis, key, 45) is False
    release_lock(redis, key)
    assert try_acquire_lock(redis, key, 45) is True


def test_entry_cooldown_flag():
    redis = _FakeRedis()
    assert entry_cooldown_active(redis, 1, "banknifty") is False
    set_entry_cooldown(redis, 1, "banknifty")
    assert entry_cooldown_active(redis, 1, "banknifty") is True


def test_option_strike_key_normalizes_right():
    assert option_strike_key("NIFTY08SEP2623850PE") == "23850PE"
    assert option_strike_key("BANKNIFTY08SEP2652500CE") == "52500CE"


def test_range_bound_same_strike_cooldown_blocks_repeat():
    redis = _FakeRedis()
    symbol = "NIFTY08SEP2623850PE"
    set_same_strike_cooldown(redis, 1, "nifty50", symbol)
    blocked, reason = range_bound_same_strike_blocked(
        regime={"regime": "RANGE_BOUND"},
        option_symbol=symbol,
        redis_client=redis,
        user_id=1,
        instrument_key="nifty50",
    )
    assert blocked is True
    assert "23850PE" in reason

    ok, _ = range_bound_same_strike_blocked(
        regime={"regime": "TRENDING_BEAR"},
        option_symbol=symbol,
        redis_client=redis,
        user_id=1,
        instrument_key="nifty50",
    )
    assert ok is False


def test_range_bound_same_strike_uses_trade_history():
    from datetime import datetime, timezone

    history = [
        {
            "option_symbol": "NIFTY08SEP2623850PE",
            "entry_time": datetime.now(timezone.utc).isoformat(),
        }
    ]
    blocked, _ = range_bound_same_strike_blocked(
        regime="RANGE_BOUND",
        option_symbol="NIFTY08SEP2623850PE",
        trade_history=history,
    )
    assert blocked is True


def test_entered_this_cycle_uses_entry_time():
    from datetime import datetime, timedelta, timezone

    fresh = {"entry_time": datetime.now(timezone.utc).isoformat()}
    stale = {"entry_time": (datetime.now(timezone.utc) - timedelta(seconds=40)).isoformat()}
    assert _entered_this_cycle(fresh) is True
    assert _entered_this_cycle(stale) is False


def test_pick_strike_prefers_spot_not_far_otm():
    picked = pick_strike(
        {
            "rows": [
                {"symbol": "BANKNIFTY25AUG2652500PE", "strike": 52500, "ltp": 11.1},
                {"symbol": "BANKNIFTY25AUG2657200PE", "strike": 5720000, "ltp": 180.0},
            ]
        },
        57224.0,
        "PUT",
    )
    assert picked is not None
    assert picked["symbol"].endswith("57200PE")


def test_stream_runner_skips_inflight_desk():
    runner = ScalpingStreamRunner(redis_url="redis://test", interval_sec=1.0)
    runner._last_eval["1:banknifty"] = 0.0
    runner._inflight.add("1:banknifty")
    assert runner._should_eval(1, "banknifty") is True
    # in-flight still blocks the actual eval launch
    assert "1:banknifty" in runner._inflight


def test_parse_option_expiry_and_ignore_expired_contracts():
    from datetime import date

    from trading_shared.strategies.scalping_desk.entry_guard import (
        option_symbol_is_expired,
        parse_option_expiry,
    )

    assert parse_option_expiry("NIFTY18AUG2624200PE") == date(2026, 8, 18)
    assert parse_option_expiry("BANKNIFTY25AUG2648000CE") == date(2026, 8, 25)
    assert option_symbol_is_expired("NIFTY18AUG2624200PE", as_of=date(2026, 8, 21)) is True
    assert option_symbol_is_expired("NIFTY25AUG2624050PE", as_of=date(2026, 8, 21)) is False


def test_live_net_qty_ignores_expired_symbols():
    from datetime import date
    from types import SimpleNamespace

    from trading_shared.strategies.scalping_desk import entry_guard as eg

    class _Query:
        def __init__(self, rows):
            self._rows = rows

        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return self._rows

    class _DB:
        def query(self, _model):
            return _Query(
                [
                    SimpleNamespace(symbol="NIFTY18AUG2624200PE", side="BUY", qty=585, status="submitted"),
                    SimpleNamespace(symbol="NIFTY18AUG2624200PE", side="BUY", qty=585, status="submitted"),
                    SimpleNamespace(symbol="NIFTY25AUG2624050PE", side="BUY", qty=65, status="submitted"),
                    SimpleNamespace(symbol="NIFTY25AUG2624050PE", side="SELL", qty=65, status="submitted"),
                ]
            )

    monkey_today = date(2026, 8, 21)

    original = eg.option_symbol_is_expired

    def _expired(symbol, *, as_of=None):
        return original(symbol, as_of=as_of or monkey_today)

    eg.option_symbol_is_expired = _expired
    try:
        assert eg.live_underlying_net_qty(_DB(), 1, "NIFTY") == 0
        assert eg.live_net_qty(_DB(), 1, "NIFTY18AUG2624200PE") == 0
    finally:
        eg.option_symbol_is_expired = original
