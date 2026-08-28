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


def test_record_live_entry_result_persists_failure_state():
    svc = ScalpingDeskService.__new__(ScalpingDeskService)
    state = {}
    signal = {
        "timestamp": "2026-08-19T03:46:00+00:00",
        "signal_type": "PUT",
        "strategy_id": "smc_orb_fvg",
        "option_symbol": "NIFTY28AUG24250PE",
        "option_token": "12345",
        "entry": 18.5,
        "lots": 2,
    }

    result = ScalpingDeskService._record_live_entry_result(
        svc,
        state,
        signal,
        {"ok": False, "reason": ["Entry cooldown after a failed or recent live order"]},
        strategy_code="SCALP-SMC-003",
    )

    assert result["ok"] is False
    assert signal["trade_entry"]["strategy_code"] == "SCALP-SMC-003"
    assert state["last_live_entry_attempt"]["signal_type"] == "PUT"
    assert state["last_live_entry_failure"]["reason"] == ["Entry cooldown after a failed or recent live order"]


def test_record_live_entry_result_clears_failure_on_success():
    svc = ScalpingDeskService.__new__(ScalpingDeskService)
    state = {"last_live_entry_failure": {"reason": ["older failure"]}}
    signal = {
        "timestamp": "2026-08-19T03:47:00+00:00",
        "signal_type": "CALL",
        "strategy_id": "smc_orb_fvg",
    }

    result = ScalpingDeskService._record_live_entry_result(
        svc,
        state,
        signal,
        {"ok": True, "order_id": "OID-1"},
        strategy_code="SCALP-SMC-003",
    )

    assert result["ok"] is True
    assert signal["trade_entry"]["order_id"] == "OID-1"
    assert state["last_live_entry_failure"] is None
