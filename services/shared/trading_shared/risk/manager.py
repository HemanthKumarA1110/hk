"""Redis-backed risk state manager."""

from __future__ import annotations

import json

import redis

from trading_shared.risk.engine import RiskEngine, RiskLimits, RiskState

REDIS_RISK_STATE_KEY = "risk:state"
REDIS_RISK_LIMITS_KEY = "risk:limits"


class RiskManager:
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url, decode_responses=True)
        self.engine = self._load_engine()

    def _load_engine(self) -> RiskEngine:
        limits_raw = self.redis.get(REDIS_RISK_LIMITS_KEY)
        state_raw = self.redis.get(REDIS_RISK_STATE_KEY)
        limits = RiskLimits(**json.loads(limits_raw)) if limits_raw else RiskLimits()
        state = RiskState(**json.loads(state_raw)) if state_raw else RiskState()
        return RiskEngine(limits, state)

    def save(self) -> None:
        self.redis.set(REDIS_RISK_LIMITS_KEY, json.dumps(self.engine.limits.__dict__))
        self.redis.set(REDIS_RISK_STATE_KEY, json.dumps(self.engine.state.to_dict()))

    def status(self) -> dict:
        self.engine.maybe_reset_day()
        return self.engine.risk_meter()

    def update_limits(self, **kwargs) -> dict:
        for key, value in kwargs.items():
            if hasattr(self.engine.limits, key) and value is not None:
                setattr(self.engine.limits, key, value)
        self.save()
        return self.engine.risk_meter()

    def set_equity(self, equity: float) -> dict:
        self.engine.update_equity(equity)
        self.save()
        return self.engine.risk_meter()

    def evaluate_trade(self, entry: float, stoploss: float, side: str) -> dict:
        can_trade, reason = self.engine.can_trade()
        sizing = self.engine.position_size(entry, stoploss)
        return {
            "approved": can_trade and sizing["qty"] > 0,
            "reason": reason,
            "position_size": sizing,
            "dynamic_stoploss": self.engine.dynamic_stoploss(entry, side),
            "risk_meter": self.engine.risk_meter(),
        }

    def register_trade(self, realized_pnl: float, notional: float = 0.0) -> dict:
        self.engine.register_trade(realized_pnl, notional)
        self.save()
        return self.engine.risk_meter()

    def reset_halt(self) -> dict:
        self.engine.state.trading_halted = False
        self.engine.state.halt_reason = ""
        self.save()
        return self.engine.risk_meter()
