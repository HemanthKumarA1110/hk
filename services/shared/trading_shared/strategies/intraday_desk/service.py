"""Intraday desk — auto-trading, AI/manual strategy selection, order placement."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime, timezone
from typing import Any

import redis
from sqlalchemy.orm import Session

from trading_shared.ai.decision_engine import DecisionEngine
from trading_shared.ai.features import FeatureExtractor
from trading_shared.ai.regime import RegimeDetector
from trading_shared.ai.learning import AdaptiveLearner
from trading_shared.config import get_settings
from trading_shared.execution.auto_trading import AutoTradingStore, compute_auto_trade_qty
from trading_shared.execution.executor import OrderExecutor, OrderRejectedError
from trading_shared.execution.paper import PaperTradeExecutor
from trading_shared.execution.trading_mode import MODE_PAPER, TradingModeStore
from trading_shared.market.redis_bus import MarketRedisBus
from trading_shared.market.scrip_master import ScripMasterService
from trading_shared.risk.manager import RiskManager
from trading_shared.schemas.order import OrderCreateRequest
from trading_shared.strategies.data_provider import StrategyDataProvider
from trading_shared.strategies.intraday_desk.catalog import default_strategy_settings, merge_strategy_settings
from trading_shared.strategies.intraday_desk.guards import guard_status
from trading_shared.strategies.intraday_desk.session import enrich_intraday_frame, is_force_exit_bar, position_qty
from trading_shared.strategies.intraday_desk.stock_picker import score_intraday_candidate
from trading_shared.strategies.intraday_desk.strategies import get_strategy
from trading_shared.strategies.intraday_engine import IntradayEngine
from trading_shared.strategies.intraday_scanner import AngelOneIntradayDataProvider

logger = logging.getLogger(__name__)

REDIS_CONFIG_PREFIX = "intraday_desk:config"
REDIS_STATE_PREFIX = "intraday_desk:state"


def default_desk_config() -> dict[str, Any]:
    return {
        "auto_trading_enabled": False,
        "strategy_mode": "ai",  # ai | manual
        "manual_strategy_code": "INTRA-ORB",
        "capital": 100_000.0,
        "max_trades_per_day": 5,
        "max_daily_loss_inr": 5000.0,
        "risk_pct": 1.0,
        "top_picks": 10,
        "intraday_strategy_settings": default_strategy_settings(),
    }


class IntradayDeskService:
    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self.settings = get_settings()
        self.redis = redis.from_url(self.settings.REDIS_URL, decode_responses=True)

    def _config_key(self) -> str:
        return f"{REDIS_CONFIG_PREFIX}:{self.user_id}"

    def _state_key(self) -> str:
        return f"{REDIS_STATE_PREFIX}:{self.user_id}"

    def get_config(self) -> dict[str, Any]:
        raw = self.redis.get(self._config_key())
        cfg = default_desk_config()
        if raw:
            loaded = json.loads(raw)
            cfg.update({k: v for k, v in loaded.items() if k in cfg or k == "intraday_strategy_settings"})
            cfg["intraday_strategy_settings"] = merge_strategy_settings(loaded)
        return cfg

    def save_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        cfg = self.get_config()
        for key in (
            "auto_trading_enabled",
            "strategy_mode",
            "manual_strategy_code",
            "capital",
            "max_trades_per_day",
            "max_daily_loss_inr",
            "risk_pct",
            "top_picks",
        ):
            if updates.get(key) is not None:
                cfg[key] = updates[key]
        if isinstance(updates.get("intraday_strategy_settings"), dict):
            cfg["intraday_strategy_settings"] = merge_strategy_settings(
                {"intraday_strategy_settings": updates["intraday_strategy_settings"]}
            )
        self.redis.set(self._config_key(), json.dumps(cfg))
        self._sync_auto_trading_store(cfg)
        return cfg

    def _sync_auto_trading_store(self, cfg: dict[str, Any]) -> None:
        """Mirror desk limits into global auto-trading intraday engine settings."""
        store = AutoTradingStore(self.settings.REDIS_URL)
        capital = float(cfg.get("capital") or 100_000)
        per_trade = capital / max(float(cfg.get("max_trades_per_day") or 5), 1)
        store.save_config(
            self.user_id,
            {
                "engine": "intraday",
                "enabled": bool(cfg.get("auto_trading_enabled")),
                "max_orders_per_day": int(cfg.get("max_trades_per_day") or 5),
                "max_order_amount": round(per_trade, 2),
            },
        )
        loss_inr = float(cfg.get("max_daily_loss_inr") or 5000)
        capital_base = max(capital, 1)
        loss_pct = min(round(loss_inr / capital_base * 100, 2), 100)
        store.save_config(self.user_id, {"max_daily_loss_pct": loss_pct})

    def get_state(self) -> dict[str, Any]:
        raw = self.redis.get(self._state_key())
        today = date.today().isoformat()
        state = {
            "day": today,
            "trades_today": 0,
            "daily_pnl": 0.0,
            "active_positions": [],
            "trade_history": [],
            "last_run_at": None,
            "last_error": None,
        }
        if raw:
            loaded = json.loads(raw)
            if loaded.get("day") == today:
                state.update(loaded)
            else:
                state["trade_history"] = (loaded.get("trade_history") or [])[-50:]
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        self.redis.set(self._state_key(), json.dumps(state))

    def toggle_auto_trading(self, enabled: bool) -> dict[str, Any]:
        cfg = self.save_config({"auto_trading_enabled": enabled})
        mode = TradingModeStore(self.settings.REDIS_URL).get(self.user_id)
        return {
            "auto_trading_enabled": enabled,
            "trading_mode": mode,
            "paper_mode": mode == MODE_PAPER,
        }

    def get_desk_payload(self) -> dict[str, Any]:
        cfg = self.get_config()
        state = self.get_state()
        guards = guard_status(state, cfg)
        mode = TradingModeStore(self.settings.REDIS_URL).get(self.user_id)
        return {
            "config": cfg,
            "state": state,
            "guards": guards,
            "trading_mode": mode,
        }

    def _build_ai_engine(self) -> DecisionEngine:
        bus = MarketRedisBus(self.settings.REDIS_URL)
        scrip = ScripMasterService(self.redis)
        data = StrategyDataProvider(bus, scrip)
        learner = AdaptiveLearner(self.db, self.redis)
        return DecisionEngine(
            FeatureExtractor(data, bus),
            RegimeDetector(data),
            learner.get_scorer(),
            enter_threshold=self.settings.AI_DECISION_THRESHOLD,
        )

    async def run_auto_cycle(self) -> dict[str, Any]:
        cfg = self.get_config()
        state = self.get_state()
        guards = guard_status(state, cfg)
        result: dict[str, Any] = {
            "executed_entries": [],
            "executed_exits": [],
            "skipped": [],
            "errors": [],
        }

        if not cfg.get("auto_trading_enabled"):
            result["skipped"].append("Auto trading disabled")
            return result

        # --- manage exits first ---
        await self._process_exits(cfg, state, guards, result)

        if not guards.get("can_enter"):
            result["skipped"].extend(guards.get("alerts") or [])
            state["last_run_at"] = datetime.now(timezone.utc).isoformat()
            self._save_state(state)
            return result

        signals = await self._collect_signals(cfg)
        if not signals:
            result["skipped"].append("No intraday signals")
            state["last_run_at"] = datetime.now(timezone.utc).isoformat()
            self._save_state(state)
            return result

        mode = cfg.get("strategy_mode", "ai")
        ai_engine = self._build_ai_engine() if mode == "ai" else None
        open_symbols = {p["symbol"] for p in state.get("active_positions") or []}
        mode_store = TradingModeStore(self.settings.REDIS_URL)
        trading_mode = mode_store.get(self.user_id)
        risk = RiskManager(self.settings.REDIS_URL)

        per_trade_capital = float(cfg.get("capital") or 100_000) / max(
            int(cfg.get("max_trades_per_day") or 5), 1
        )

        for signal in signals:
            if int(state.get("trades_today") or 0) >= int(cfg.get("max_trades_per_day") or 5):
                break
            symbol = signal.get("symbol")
            if not symbol or symbol in open_symbols:
                continue

            if mode == "ai":
                decision = ai_engine.evaluate_signal(signal, has_open_position=False).to_dict()
                if decision.get("action") not in ("enter", "scale_in"):
                    result["skipped"].append(f"{symbol}: AI rejected ({decision.get('action')})")
                    continue
                size_pct = float(decision.get("recommended_size_pct") or 100)
            else:
                size_pct = 100.0

            side = str(signal.get("side", "BUY")).upper()
            entry = float(signal.get("entry") or 0)
            stoploss = float(signal.get("stoploss") or entry * 0.99)
            if entry <= 0:
                continue

            evaluation = risk.evaluate_trade(entry, stoploss, side)
            if not evaluation["approved"]:
                result["skipped"].append(f"{symbol}: {evaluation['reason']}")
                continue

            risk_qty = int(evaluation["position_size"]["qty"] or 0)
            qty, _ = compute_auto_trade_qty(entry, per_trade_capital, size_pct, risk_qty)
            if qty < 1:
                qty = position_qty(float(cfg.get("capital") or 100_000), entry, stoploss, float(cfg.get("risk_pct") or 1))
            if qty < 1:
                result["skipped"].append(f"{symbol}: unable to size order")
                continue

            payload = OrderCreateRequest(
                symbol=symbol,
                symboltoken=str(signal.get("token")) if signal.get("token") else None,
                exchange="NSE",
                side=side,
                qty=qty,
                order_type="MARKET",
                price=entry,
                stoploss=stoploss,
                product="INTRADAY",
            )

            try:
                if trading_mode == MODE_PAPER:
                    order = await PaperTradeExecutor(self.db, self.user_id).place_order(
                        payload,
                        desk="intraday",
                        strategy_code=signal.get("metadata", {}).get("strategy_code"),
                    )
                else:
                    order = await OrderExecutor(self.db, self.user_id).place_order(payload)

                position = {
                    "symbol": symbol,
                    "token": signal.get("token"),
                    "side": side,
                    "qty": qty,
                    "entry": entry,
                    "stoploss": stoploss,
                    "target": float((signal.get("targets") or [entry])[0]),
                    "strategy_code": signal.get("metadata", {}).get("strategy_code"),
                    "strategy_id": signal.get("strategy_name"),
                    "entry_time": datetime.now(timezone.utc).isoformat(),
                    "order_id": order.get("broker_order_id") or order.get("id"),
                }
                state.setdefault("active_positions", []).append(position)
                open_symbols.add(symbol)
                state["trades_today"] = int(state.get("trades_today") or 0) + 1
                result["executed_entries"].append(
                    {"symbol": symbol, "qty": qty, "entry": entry, "mode": trading_mode, "strategy": position["strategy_code"]}
                )
            except OrderRejectedError as exc:
                result["errors"].append(f"{symbol}: {exc}")
            except Exception as exc:
                logger.exception("Intraday auto entry failed for %s", symbol)
                result["errors"].append(f"{symbol}: {exc}")

        state["last_run_at"] = datetime.now(timezone.utc).isoformat()
        state["last_error"] = result["errors"][-1] if result["errors"] else None
        self._save_state(state)
        return result

    async def _collect_signals(self, cfg: dict[str, Any]) -> list[dict]:
        scrip = ScripMasterService(self.redis)
        if not scrip.ensure_loaded():
            return []

        provider = AngelOneIntradayDataProvider(
            MarketRedisBus(self.settings.REDIS_URL),
            scrip,
            self.db,
            self.user_id,
        )
        await provider.prepare()

        engine = IntradayEngine(provider, config=cfg)
        mode = cfg.get("strategy_mode", "ai")
        if mode == "manual":
            code = cfg.get("manual_strategy_code") or "INTRA-ORB"
            raw_signals = engine.evaluate(limit=int(cfg.get("top_picks") or 10), strategy_filter=code)
        else:
            raw_signals = engine.evaluate(limit=int(cfg.get("top_picks") or 10))

        scored: list[tuple[float, dict]] = []
        for sig in raw_signals:
            sig_dict = sig.to_dict() if hasattr(sig, "to_dict") else sig
            token = sig_dict.get("token")
            symbol = sig_dict.get("symbol")
            if not token:
                continue
            df = provider.build_intraday_frame(token, symbol, bars=80)
            if len(df) < 25:
                continue
            score = score_intraday_candidate(
                enrich_intraday_frame(df) if "timestamp" in df.columns else df,
                sig_dict.get("metadata", {}).get("strategy_code") or cfg.get("manual_strategy_code") or "INTRA-ORB",
            )
            scored.append((score, sig_dict))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [s for _, s in scored[: int(cfg.get("top_picks") or 10)]]

    async def _process_exits(
        self,
        cfg: dict[str, Any],
        state: dict[str, Any],
        guards: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        positions = list(state.get("active_positions") or [])
        if not positions:
            return

        scrip = ScripMasterService(self.redis)
        provider = AngelOneIntradayDataProvider(
            MarketRedisBus(self.settings.REDIS_URL),
            scrip,
            self.db,
            self.user_id,
        )
        await provider.prepare()
        ai_engine = self._build_ai_engine() if cfg.get("strategy_mode") == "ai" else None
        trading_mode = TradingModeStore(self.settings.REDIS_URL).get(self.user_id)
        remaining = []

        for pos in positions:
            symbol = pos["symbol"]
            token = pos.get("token")
            df = provider.build_intraday_frame(str(token), symbol, bars=80)
            if len(df) < 25 or "timestamp" not in df.columns:
                remaining.append(pos)
                continue

            enriched = enrich_intraday_frame(df)
            idx = len(enriched) - 1
            row = enriched.iloc[idx]
            exit_price = None
            exit_reason = ""

            if guards.get("must_force_exit") or is_force_exit_bar(row["timestamp"]):
                exit_price = float(row["close"])
                exit_reason = "eod"
            else:
                code = pos.get("strategy_code") or "INTRA-ORB"
                try:
                    strategy = get_strategy(strategy_code=code)
                    hit = strategy.try_exit(
                        {
                            "side": pos.get("side", "BUY"),
                            "entry_price": pos["entry"],
                            "stoploss": pos["stoploss"],
                            "target": pos.get("target"),
                            "trailing_pct": None,
                            "entry_idx": 0,
                        },
                        enriched,
                        idx,
                    )
                    if hit:
                        exit_price, exit_reason = hit
                except ValueError:
                    pass

                if exit_price is None and ai_engine and cfg.get("strategy_mode") == "ai":
                    from trading_shared.ai.trade_reasoning import evaluate_dynamic_exit

                    ltp = float(row["close"])
                    entry = float(pos["entry"])
                    dynamic = evaluate_dynamic_exit(
                        engine="intraday",
                        side=pos.get("side", "BUY"),
                        entry=entry,
                        stop=float(pos["stoploss"]),
                        target=float(pos["target"]) if pos.get("target") else None,
                        strategy=code,
                        current=ltp,
                        candles=enriched.tail(30),
                        vwap=float(row.get("vwap") or ltp),
                    )
                    if dynamic.get("should_exit"):
                        exit_price = ltp
                        exit_reason = "dynamic_exit"
                    else:
                        pnl_pct = ((ltp - entry) / entry * 100) if entry else 0
                        fake_signal = {"symbol": symbol, "engine": "intraday", "side": pos.get("side", "BUY")}
                        decision = ai_engine.evaluate_signal(
                            fake_signal, has_open_position=True, position_pnl_pct=pnl_pct
                        )
                        if decision.action.value == "exit":
                            exit_price = ltp
                            exit_reason = "ai_exit"

            if exit_price is None:
                remaining.append(pos)
                continue

            try:
                payload = OrderCreateRequest(
                    symbol=symbol,
                    symboltoken=str(token) if token else None,
                    exchange="NSE",
                    side="SELL" if pos.get("side", "BUY") == "BUY" else "BUY",
                    qty=int(pos["qty"]),
                    order_type="MARKET",
                    price=exit_price,
                    product="INTRADAY",
                )
                if trading_mode == MODE_PAPER:
                    await PaperTradeExecutor(self.db, self.user_id).close_open_order(
                        symbol=symbol,
                        exit_price=exit_price,
                        reason=exit_reason,
                    )
                else:
                    await OrderExecutor(self.db, self.user_id).place_order(payload)

                pnl = (exit_price - float(pos["entry"])) * int(pos["qty"])
                if pos.get("side") == "SELL":
                    pnl = -pnl
                state["daily_pnl"] = round(float(state.get("daily_pnl") or 0) + pnl, 2)
                closed = {**pos, "exit": exit_price, "exit_reason": exit_reason, "pnl": round(pnl, 2)}
                state.setdefault("trade_history", []).append(closed)
                state["trade_history"] = state["trade_history"][-100:]
                result["executed_exits"].append({"symbol": symbol, "pnl": round(pnl, 2), "reason": exit_reason})
            except Exception as exc:
                logger.exception("Intraday exit failed for %s", symbol)
                result["errors"].append(f"Exit {symbol}: {exc}")
                remaining.append(pos)

        state["active_positions"] = remaining


def run_intraday_desk_auto_sync(db: Session, user_id: int) -> dict:
    service = IntradayDeskService(db, user_id)
    return asyncio.run(service.run_auto_cycle())


def iter_auto_enabled_users(redis_url: str) -> list[int]:
    client = redis.from_url(redis_url, decode_responses=True)
    users = []
    for key in client.scan_iter(f"{REDIS_CONFIG_PREFIX}:*"):
        uid = int(key.rsplit(":", 1)[-1])
        raw = client.get(key)
        if raw and json.loads(raw).get("auto_trading_enabled"):
            users.append(uid)
    return users
