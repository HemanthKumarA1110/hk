import json

from trading_shared.strategies.scalping_desk.constants import REDIS_CONFIG_SUFFIX, REDIS_DESK_PREFIX
from trading_shared.strategies.scalping_desk.service import iter_auto_enabled_desks


class _FakeRedis:
    def __init__(self, keys: dict[str, str]):
        self.keys = keys

    def scan_iter(self, pattern: str):
        prefix = pattern.replace("*", "")
        for key in self.keys:
            if key.endswith(REDIS_CONFIG_SUFFIX) and key.startswith(f"{REDIS_DESK_PREFIX}:"):
                yield key

    def get(self, key):
        return self.keys.get(key)


def test_iter_auto_enabled_desks_filters_by_flag(monkeypatch):
    keys = {
        "scalping:desk:1:nifty50:config": json.dumps({"auto_trading_enabled": True, "capital": 150000}),
        "scalping:desk:1:banknifty:config": json.dumps({"auto_trading_enabled": False, "capital": 50000}),
        "scalping:desk:2:nifty50:config": json.dumps({"auto_trading_enabled": True, "capital": 100000}),
        "scalping:desk:1:unknown:config": json.dumps({"auto_trading_enabled": True}),
    }
    fake = _FakeRedis(keys)
    monkeypatch.setattr(
        "trading_shared.strategies.scalping_desk.service.redis.from_url",
        lambda _url, decode_responses=True: fake,
    )

    desks = iter_auto_enabled_desks("redis://test")
    assert sorted(desks) == [(1, "nifty50"), (2, "nifty50")]
