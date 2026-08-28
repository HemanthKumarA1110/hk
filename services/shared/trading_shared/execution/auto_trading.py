"""Auto-trading: execute AI-approved strategy signals with risk limits."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timezone

import redis
from sqlalchemy.orm import Session

from trading_shared.ai.orchestrator import AIOrchestrator
from trading_shared.execution.executor import OrderExecutor, OrderRejectedError
from trading_shared.execution.trading_mode import TradingModeStore
from trading_shared.risk.manager import RiskManager
from trading_shared.schemas.order import OrderCreateRequest

logger = logging.getLogger(__name__)

REDIS_AUTO_CONFIG_PREFIX = "auto_trading:config"
REDIS_AUTO_STATS_PREFIX = "auto_trading:stats"
REDIS_AUTO_EXECUTED_PREFIX = "auto_trading:executed"
DEFAULT_ENGINES = ("scalping", "intraday", "swing")
AUTO_ACTIONS = ("enter", "scale_in")

ENGINE_PRODUCTS = {
    "scalping": "INTRADAY",
    "intraday": "INTRADAY",
    "swing": "DELIVERY",
}

ENGINE_LABELS = {
    "scalping": "Scalping (NIFTY / BANKNIFTY)",
    "intraday": "Intraday",
    "swing": "Swing",
}


def default_engine_settings() -> dict[str, dict]:
    return {
        engine: {
            "enabled": False,
            "max_orders_per_day": 10,
            "max_order_amount": 0.0,
            "product": ENGINE_PRODUCTS[engine],
        }
        for engine in DEFAULT_ENGINES
    }


def compute_auto_trade_qty(
    entry: float,
    max_order_amount: float,
    recommended_size_pct: float,
    risk_qty: int,
) -> tuple[int, float]:
    """Size order from max INR amount; cap by risk engine qty when set."""
    if entry <= 0:
        return 0, 0.0

    size_pct = max(0.0, min(float(recommended_size_pct or 100), 100.0))

    if max_order_amount > 0:
        budget = max_order_amount * (size_pct / 100.0)
        qty = int(budget // entry)
        if qty < 1:
            return 0, 0.0
        if risk_qty > 0:
            qty = min(qty, risk_qty)
        return qty, round(qty * entry, 2)

    if risk_qty <= 0:
        return 0, 0.0
    qty = max(1, int(risk_qty * size_pct / 100))
    return qty, round(qty * entry, 2)


def default_stats() -> dict:
    today = date.today().isoformat()
    return {
        "orders_today": 0,
        "last_run_at": None,
        "last_order_at": None,
        "last_error": None,
        "day": today,
        "engines": {
            engine: {
                "orders_today": 0,
                "last_run_at": None,
                "last_order_at": None,
                "last_error": None,
            }
            for engine in DEFAULT_ENGINES
        },
    }


class AutoTradingStore:
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url, decode_responses=True)

    def _config_key(self, user_id: int) -> str:
        return f"{REDIS_AUTO_CONFIG_PREFIX}:{user_id}"

    def _stats_key(self, user_id: int) -> str:
        return f"{REDIS_AUTO_STATS_PREFIX}:{user_id}"

    def default_config(self) -> dict:
        return {
            "max_daily_loss_pct": 5.0,
            "engine_settings": default_engine_settings(),
        }

    def _normalize_config(self, raw: dict) -> dict:
        config = self.default_config()
        config.update({k: v for k, v in raw.items() if k in ("max_daily_loss_pct",)})

        settings = default_engine_settings()
        if isinstance(raw.get("engine_settings"), dict):
            for engine in DEFAULT_ENGINES:
                if engine in raw["engine_settings"]:
                    settings[engine].update(raw["engine_settings"][engine])
        elif isinstance(raw.get("engines"), list):
            legacy_enabled = bool(raw.get("enabled"))
            legacy_max = int(raw.get("max_orders_per_day", 10))
            for engine in DEFAULT_ENGINES:
                settings[engine]["enabled"] = legacy_enabled and engine in raw["engines"]
                settings[engine]["max_orders_per_day"] = legacy_max
        elif raw.get("enabled"):
            for engine in DEFAULT_ENGINES:
                settings[engine]["enabled"] = True
                settings[engine]["max_orders_per_day"] = int(raw.get("max_orders_per_day", 10))

        config["engine_settings"] = settings
        return config

    def get_config(self, user_id: int) -> dict:
        raw = self.redis.get(self._config_key(user_id))
        if not raw:
            return self.default_config()
        return self._normalize_config(json.loads(raw))

    def save_config(self, user_id: int, updates: dict) -> dict:
        current = self.get_config(user_id)

        if updates.get("max_daily_loss_pct") is not None:
            current["max_daily_loss_pct"] = updates["max_daily_loss_pct"]

        engine = updates.get("engine")
        if engine and engine in DEFAULT_ENGINES:
            engine_updates = {
                k: updates[k]
                for k in ("enabled", "max_orders_per_day", "max_order_amount")
                if updates.get(k) is not None
            }
            if "max_order_amount" in engine_updates:
                engine_updates["max_order_amount"] = float(engine_updates["max_order_amount"])
            current["engine_settings"][engine].update(engine_updates)

        self.redis.set(self._config_key(user_id), json.dumps(current))
        return current

    def is_engine_enabled(self, config: dict, engine: str) -> bool:
        settings = config.get("engine_settings") or {}
        return bool(settings.get(engine, {}).get("enabled"))

    def any_engine_enabled(self, config: dict) -> bool:
        return any(self.is_engine_enabled(config, engine) for engine in DEFAULT_ENGINES)

    def enabled_engines(self, config: dict) -> list[str]:
        return [engine for engine in DEFAULT_ENGINES if self.is_engine_enabled(config, engine)]

    def get_stats(self, user_id: int) -> dict:
        raw = self.redis.get(self._stats_key(user_id))
        stats = default_stats()
        if raw:
            loaded = json.loads(raw)
            stats.update({k: v for k, v in loaded.items() if k != "engines"})
            for engine in DEFAULT_ENGINES:
                if isinstance(loaded.get("engines"), dict) and engine in loaded["engines"]:
                    stats["engines"][engine].update(loaded["engines"][engine])

        today = date.today().isoformat()
        if stats.get("day") != today:
            stats["orders_today"] = 0
            stats["day"] = today
            for engine in DEFAULT_ENGINES:
                stats["engines"][engine]["orders_today"] = 0

        stats["orders_today"] = sum(stats["engines"][engine]["orders_today"] for engine in DEFAULT_ENGINES)
        return stats

    def save_stats(self, user_id: int, stats: dict) -> None:
        self.redis.set(self._stats_key(user_id), json.dumps(stats))

    def iter_enabled_users(self) -> list[tuple[int, dict]]:
        enabled: list[tuple[int, dict]] = []
        for key in self.redis.scan_iter(f"{REDIS_AUTO_CONFIG_PREFIX}:*"):
            user_id = int(key.rsplit(":", 1)[-1])
            config = self.get_config(user_id)
            if self.any_engine_enabled(config):
                enabled.append((user_id, config))
        return enabled


class AutoTradingRunner:
    def __init__(self, db: Session, redis_url: str):
        self.db = db
        self.redis_url = redis_url
        self.store = AutoTradingStore(redis_url)
        self.redis = redis.from_url(redis_url, decode_responses=True)

    async def run_for_user(self, user_id: int, config: dict | None = None, engine_filter: str | None = None) -> dict:
        config = config or self.store.get_config(user_id)
        stats = self.store.get_stats(user_id)
        result = {
            "user_id": user_id,
            "executed": [],
            "skipped": [],
            "errors": [],
        }

        enabled_engines = self.store.enabled_engines(config)
        if engine_filter:
            if engine_filter not in DEFAULT_ENGINES:
                result["skipped"].append(f"Unknown engine: {engine_filter}")
                return result
            if not self.store.is_engine_enabled(config, engine_filter):
                result["skipped"].append(f"{ENGINE_LABELS.get(engine_filter, engine_filter)} auto trading disabled")
                return result
            enabled_engines = [engine_filter]
        elif not enabled_engines:
            result["skipped"].append("Auto trading disabled for all engines")
            return result

        risk = RiskManager(self.redis_url)
        risk.update_limits(max_daily_loss_pct=config.get("max_daily_loss_pct"))

        can_trade, reason = risk.engine.can_trade()
        if not can_trade:
            stats["last_error"] = reason
            stats["last_run_at"] = datetime.now(timezone.utc).isoformat()
            for engine in enabled_engines:
                stats["engines"][engine]["last_error"] = reason
                stats["engines"][engine]["last_run_at"] = stats["last_run_at"]
            self.store.save_stats(user_id, stats)
            result["skipped"].append(reason)
            return result

        ai_payload = AIOrchestrator.get_cached()
        allowed_engines = set(enabled_engines)
        approved = [
            d
            for d in ai_payload.get("approved", [])
            if d.get("action") in AUTO_ACTIONS and d.get("engine") in allowed_engines
        ]

        mode = TradingModeStore(self.redis_url).get(user_id)
        engine_settings = config.get("engine_settings") or default_engine_settings()

        for decision in approved:
            engine = str(decision.get("engine") or "")
            engine_cfg = engine_settings.get(engine, {})
            engine_stats = stats["engines"][engine]
            max_orders = int(engine_cfg.get("max_orders_per_day", 10))

            if engine_stats["orders_today"] >= max_orders:
                result["skipped"].append(f"{ENGINE_LABELS.get(engine, engine)}: max orders per day reached")
                continue

            signal = decision.get("signal") or {}
            symbol = decision.get("symbol") or signal.get("symbol")
            dedupe_key = f"{REDIS_AUTO_EXECUTED_PREFIX}:{user_id}:{date.today().isoformat()}:{engine}:{symbol}:{decision.get('action')}"
            if self.redis.get(dedupe_key):
                result["skipped"].append(f"Already executed {symbol}")
                continue

            side = str(signal.get("side", "BUY")).upper()
            entry = float(signal.get("entry") or 0)
            stoploss = float(signal.get("stoploss") or 0)
            if entry <= 0:
                result["skipped"].append(f"No entry price for {symbol}")
                continue

            evaluation = risk.evaluate_trade(entry, stoploss or entry * 0.995, side)
            if not evaluation["approved"]:
                result["skipped"].append(f"{symbol}: {evaluation['reason']}")
                continue

            max_order_amount = float(engine_cfg.get("max_order_amount") or 0)
            size_pct = float(decision.get("recommended_size_pct") or 100)
            risk_qty = int(evaluation["position_size"]["qty"] or 0)
            qty, notional = compute_auto_trade_qty(entry, max_order_amount, size_pct, risk_qty)

            if qty < 1:
                if max_order_amount > 0:
                    result["skipped"].append(
                        f"{symbol}: max order amount ₹{max_order_amount:,.0f} too low for 1 share at ₹{entry:,.2f}"
                    )
                else:
                    result["skipped"].append(f"{symbol}: unable to size order — set max order amount or check risk limits")
                continue

            payload = OrderCreateRequest(
                symbol=symbol,
                symboltoken=str(signal.get("token")) if signal.get("token") else None,
                exchange="NSE",
                side=side,
                qty=qty,
                order_type="MARKET",
                price=entry,
                stoploss=stoploss if stoploss > 0 else None,
                product=engine_cfg.get("product") or ENGINE_PRODUCTS.get(engine, "INTRADAY"),
            )

            try:
                executor = OrderExecutor(self.db, user_id)
                order = await executor.place_order(payload)
                self.redis.setex(dedupe_key, 86400, order.get("broker_order_id") or str(order.get("id")))
                now = datetime.now(timezone.utc).isoformat()
                engine_stats["orders_today"] += 1
                engine_stats["last_order_at"] = now
                engine_stats["last_error"] = None
                stats["last_order_at"] = now
                result["executed"].append(
                    {
                        "symbol": symbol,
                        "side": side,
                        "qty": qty,
                        "notional": notional,
                        "max_order_amount": max_order_amount,
                        "order_id": order.get("broker_order_id") or order.get("id"),
                        "mode": mode,
                        "engine": engine,
                        "ai_score": decision.get("score"),
                    }
                )
                logger.info("Auto-traded %s %s x%s for user %s (%s)", side, symbol, qty, user_id, engine)
            except OrderRejectedError as exc:
                result["errors"].append(f"{symbol}: {exc}")
                engine_stats["last_error"] = str(exc)
            except Exception as exc:
                logger.exception("Auto trade failed for %s", symbol)
                result["errors"].append(f"{symbol}: {exc}")
                engine_stats["last_error"] = str(exc)

        now = datetime.now(timezone.utc).isoformat()
        stats["last_run_at"] = now
        for engine in enabled_engines:
            stats["engines"][engine]["last_run_at"] = now
            if result["errors"] and not stats["engines"][engine]["last_error"]:
                stats["engines"][engine]["last_error"] = result["errors"][-1]
        if result["errors"]:
            stats["last_error"] = result["errors"][-1]
        elif result["executed"]:
            stats["last_error"] = None
        stats["orders_today"] = sum(stats["engines"][e]["orders_today"] for e in DEFAULT_ENGINES)
        self.store.save_stats(user_id, stats)
        return result

    async def run_all_enabled(self) -> dict:
        results = []
        for user_id, config in self.store.iter_enabled_users():
            results.append(await self.run_for_user(user_id, config))
        return {"users": len(results), "results": results}

    def status_for_user(self, user_id: int) -> dict:
        config = self.store.get_config(user_id)
        stats = self.store.get_stats(user_id)
        risk = RiskManager(self.redis_url).status()
        mode = TradingModeStore(self.redis_url).get(user_id)
        ai_payload = AIOrchestrator.get_cached()
        approved = [
            d
            for d in ai_payload.get("approved", [])
            if d.get("action") in AUTO_ACTIONS
        ]

        engines_status = {}
        for engine in DEFAULT_ENGINES:
            engine_cfg = config["engine_settings"][engine]
            engine_stats = stats["engines"][engine]
            pending = len([d for d in approved if d.get("engine") == engine])
            engines_status[engine] = {
                "label": ENGINE_LABELS[engine],
                "config": engine_cfg,
                "stats": engine_stats,
                "product": engine_cfg.get("product") or ENGINE_PRODUCTS[engine],
                "ai_approvals": pending,
            }

        return {
            "config": {
                "max_daily_loss_pct": config.get("max_daily_loss_pct"),
                "engine_settings": config.get("engine_settings"),
                "any_enabled": self.store.any_engine_enabled(config),
            },
            "engines": engines_status,
            "stats": stats,
            "trading_mode": mode,
            "risk": {
                "can_trade": risk.get("can_trade"),
                "daily_loss_used_pct": risk.get("daily_loss_used_pct"),
                "limits": risk.get("limits"),
                "state": risk.get("state"),
            },
            "ai": {
                "generated_at": ai_payload.get("generated_at"),
                "approved_signals": len(approved),
            },
        }


def run_auto_trading_sync(db: Session, redis_url: str) -> dict:
    runner = AutoTradingRunner(db, redis_url)
    return asyncio.run(runner.run_all_enabled())
