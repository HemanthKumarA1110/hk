from datetime import datetime, timedelta, timezone

from trading_shared.strategies.scalping_desk.service import ScalpingDeskService


class _StubService:
    settings = type("S", (), {"SCALPING_STREAM_INTERVAL_SEC": 1.0})()

    def _age_seconds(self, iso):
        return ScalpingDeskService._age_seconds(self, iso)

    def _evals_per_minute(self, state):
        return ScalpingDeskService._evals_per_minute(self, state)


def test_evals_per_minute_counts_recent_history():
    svc = _StubService()
    now = datetime.now(timezone.utc)
    state = {
        "stream_eval_history": [
            (now - timedelta(seconds=10)).isoformat(),
            (now - timedelta(seconds=20)).isoformat(),
            (now - timedelta(seconds=70)).isoformat(),
        ]
    }
    assert svc._evals_per_minute(state) == 2


def test_record_stream_eval_trims_old_entries():
    svc = ScalpingDeskService.__new__(ScalpingDeskService)
    now = datetime.now(timezone.utc)
    state = {
        "stream_eval_history": [(now - timedelta(seconds=130)).isoformat()],
    }
    ScalpingDeskService._record_stream_eval(svc, state)
    assert len(state["stream_eval_history"]) == 1
    assert state["last_stream_eval_at"] == state["stream_eval_history"][0]
