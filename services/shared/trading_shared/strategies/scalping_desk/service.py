"""Scalping desk orchestration — live data, signals, guards, backtest."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import redis
from sqlalchemy.orm import Session

from trading_shared.backtest.data_loader import BacktestDataLoader
from trading_shared.backtest.data_loader import INTERVAL_MAP as LOADER_INTERVAL_MAP
from trading_shared.market.candle_window import (
    angel_candle_window,
    angel_rate_limit_wait_sec,
    classify_angel_chunk_error,
)
from trading_shared.broker.angel_one.exceptions import AngelOneAPIError, AngelOneAuthError
from trading_shared.broker.angel_one.funds import parse_rms_funds
from trading_shared.broker.angel_one.schemas import CandleRequest, PlaceOrderRequest
from trading_shared.broker.angel_one.session_manager import AngelOneSessionManager
from trading_shared.config import get_settings
from trading_shared.db.session import SessionLocal
from trading_shared.execution.trading_mode import TradingModeStore
from trading_shared.execution.executor import OrderExecutor, OrderRejectedError
from trading_shared.execution.qty import chunk_order_qty, snap_qty_to_lot, NFO_MAX_ORDER_QTY
from trading_shared.schemas.order import OrderCreateRequest
from trading_shared.strategies.scalping_desk.entry_guard import (
    ENTRY_LOCK_TTL_SEC,
    entry_cooldown_active,
    entry_lock_key,
    live_net_qty,
    live_underlying_net_qty,
    release_lock,
    set_entry_cooldown,
    try_acquire_lock,
)
from trading_shared.market.redis_bus import MarketRedisBus
from trading_shared.market.scrip_master import ScripMasterService
from trading_shared.strategies.data_provider import StrategyDataProvider

from trading_shared.strategies.scalping_desk.ai_decision import (
    apply_ai_targets,
    evaluate_ai_decision,
    evaluate_ai_exit,
    optimize_strategy_prompt,
    save_optimization_history,
)
from trading_shared.strategies.scalping_desk.position_sizer import compute_dynamic_position_size, size_from_signal_context
from trading_shared.strategies.scalping_desk.trailing_sl_manager import apply_trailing_to_trade, manage_trailing_sl
from trading_shared.strategies.scalping_desk.market_regime_classifier import (
    classify_from_market_context,
    merge_regime_into_context,
)
from trading_shared.strategies.scalping_desk.mtf_context_builder import build_mtf_analysis, merge_mtf_into_context
from trading_shared.strategies.scalping_desk.orb_breakout_confirmation import confirm_orb_from_df, orb_confirmation_allows_entry
from trading_shared.strategies.scalping_desk.expiry_day_handler import (
    apply_expiry_restriction_toggle,
    expiry_allows_signal,
    handle_expiry_day,
    is_instrument_expiry_day,
    to_ist,
)
from trading_shared.strategies.scalping_desk.daily_stop import (
    apply_daily_stop,
    evaluate_ai_daily_stop,
    maybe_reset_daily_state,
    record_trade_result,
    trading_day_key,
)
from trading_shared.strategies.scalping_desk.eod_self_review import run_eod_self_review, save_eod_review
from trading_shared.strategies.scalping_desk.weekly_parameter_tuner import (
    build_session_summary,
    config_patch_from_tuning,
    save_weekly_tuning,
    tune_weekly_parameters,
)
from trading_shared.strategies.scalping_desk.pattern_memory_logger import (
    load_pattern_memory,
    log_trade_pattern,
    match_signal_to_memory,
    save_pattern_memory,
)
from trading_shared.strategies.scalping_desk.loss_trade_autopsy import (
    autopsy_losing_trade,
    load_loss_autopsies,
    save_loss_autopsy,
)
from trading_shared.strategies.scalping_desk.win_trade_reinforcement import (
    load_win_reinforcements,
    reinforce_winning_trade,
    save_win_reinforcement,
)
from trading_shared.strategies.scalping_desk.market_context import build_market_context
from trading_shared.strategies.scalping_desk.constants import (
    AI_CONFIDENCE_ENTER,
    INSTRUMENTS,
    REDIS_CONFIG_SUFFIX,
    REDIS_DESK_PREFIX,
    REDIS_STATE_SUFFIX,
    REDIS_STREAM_WORKER_HEARTBEAT,
    SCALP_EXECUTION_POLICY,
    STRATEGY_LABEL,
    STRATEGY_VERSION,
    validate_option_buy_contract,
)
from trading_shared.strategies.scalping_desk.engine import (
    classify_strikes,
    compute_scalp_risk,
    enrich_candles,
    estimate_option_mark_premium,
    max_hold_bars,
    normalize_long_premium_levels,
    risk_profile,
    should_exit,
    should_exit_index,
)
from trading_shared.strategies.scalping_desk.option_execution import ensure_buy_only_signal
from trading_shared.strategies.scalping_desk.guards import guard_status
from trading_shared.strategies.scalping_desk.entry_signal_validator import verdict_allows_entry
from trading_shared.strategies.scalping_desk.capital_utilization import (
    compute_utilization_lots,
    ensure_session_capital,
    is_index_scalp_desk,
    lots_affordable_from_cash,
    parse_insufficient_funds_amounts,
)
from trading_shared.strategies.scalping_desk.strategy_selector import (
    all_strategy_families,
    registry_for_api,
    select_and_evaluate,
    select_from_catalog,
)
from trading_shared.strategies.scalping_desk.strategy_catalog import (
    CATALOG_VERSION,
    catalog_for_api,
    default_strategy_settings,
    default_fixed_strategy_code,
    normalize_desk_config,
    resolve_strategy_code,
    strategy_setting,
)
from trading_shared.strategies.strategy_code_validation import filter_catalog_for_engine, validate_strategy_code_for_engine
from trading_shared.strategies.scalping_desk.smc_backtest import run_full_smc_pipeline
from trading_shared.strategies.scalping_desk.smc_scalping_engine import DEFAULT_SMC_PARAMS
from trading_shared.strategies.scalping_desk.orb_breakout_tuning import (
    ORB_BREAKOUT_BANK_DEFAULTS,
    ORB_BREAKOUT_NIFTY_DEFAULTS,
)
from trading_shared.strategies.scalping_desk.vwap_bounce_tuning import VWAP_BOUNCE_NIFTY_DEFAULTS
from trading_shared.strategies.scalping_desk.ema_crossover_tuning import EMA_CROSSOVER_BANK_DEFAULTS
from trading_shared.strategies.scalping_desk.smc_orb_fvg_tuning import (
    SMC_ORB_FVG_BANK_DEFAULTS,
    SMC_ORB_FVG_NIFTY_DEFAULTS,
)
from trading_shared.strategies.scalping_desk.backtest import run_backtest, run_strategy_backtest

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

SMC_JOB_TTL = 7200
DESK_JOB_TTL = 7200
BACKTEST_MAX_DAYS = 60
BACKTEST_MIN_BARS = 30
BACKTEST_CHUNK_DAYS = 5
BACKTEST_CHUNK_DELAY_SEC = 2.5
BACKTEST_CHUNK_RETRIES = 5
BACKTEST_RATE_LIMIT_WAIT_SEC = 25.0
BACKTEST_MIN_COVERAGE_RATIO = 0.25
BARS_PER_TRADING_DAY_1M = 375


def _entry_bars_held(trade: dict[str, Any], *, candle_count: int = 0) -> int:
    """Minutes held since entry (1m bar equivalents for max-hold exits)."""
    entry_time = trade.get("entry_time")
    if entry_time:
        try:
            dt = datetime.fromisoformat(str(entry_time).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            elapsed_sec = (datetime.now(timezone.utc) - dt).total_seconds()
            return max(0, int(elapsed_sec / 60))
        except ValueError:
            pass
    entry_index = int(trade.get("entry_index") or 0)
    if entry_index and candle_count > 0:
        return max(0, candle_count - 1 - entry_index)
    return int(trade.get("bars_held") or 0)


def _entered_this_cycle(trade: dict[str, Any], *, grace_sec: int = 20) -> bool:
    """Skip same-tick exit checks so a fresh fill is not flattened immediately."""
    entry_time = trade.get("entry_time")
    if not entry_time:
        return False
    try:
        dt = datetime.fromisoformat(str(entry_time).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() < grace_sec
    except ValueError:
        return False


def _expected_backtest_bars(from_date: str, to_date: str, timeframe: str) -> int:
    """Rough minimum bars for a meaningful replay (session-filtered 1m scalping)."""
    if timeframe != "1m":
        return BACKTEST_MIN_BARS
    try:
        start = datetime.strptime(from_date[:10], "%Y-%m-%d").date()
        end = datetime.strptime(to_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return BACKTEST_MIN_BARS
    calendar_days = max(1, (end - start).days + 1)
    trading_days = max(1, int(calendar_days * 5 / 7))
    return trading_days * BARS_PER_TRADING_DAY_1M


def _merge_ohlcv(*frames: pd.DataFrame) -> pd.DataFrame:
    parts = [f for f in frames if f is not None and not f.empty]
    if not parts:
        return pd.DataFrame()
    merged = pd.concat(parts, ignore_index=True)
    merged["timestamp"] = pd.to_datetime(merged["timestamp"], errors="coerce", utc=True)
    return merged.dropna(subset=["timestamp"]).drop_duplicates(subset=["timestamp"]).sort_values(
        "timestamp"
    ).reset_index(drop=True)


def _desk_job_key(user_id: int, job_id: str) -> str:
    return f"desk:job:{user_id}:{job_id}"


def _smc_job_key(user_id: int, job_id: str) -> str:
    return _desk_job_key(user_id, job_id)


def _redis_client() -> redis.Redis:
    return redis.from_url(get_settings().REDIS_URL, decode_responses=True)


def _write_desk_job(redis_client: redis.Redis, user_id: int, job_id: str, payload: dict[str, Any]) -> None:
    redis_client.setex(_desk_job_key(user_id, job_id), DESK_JOB_TTL, json.dumps(payload, default=str))


def _write_smc_job(redis_client: redis.Redis, user_id: int, job_id: str, payload: dict[str, Any]) -> None:
    _write_desk_job(redis_client, user_id, job_id, payload)


def fetch_desk_backtest_job(user_id: int, job_id: str) -> dict[str, Any]:
    """Poll any desk backtest job from Redis — no DB connection."""
    raw = _redis_client().get(_desk_job_key(user_id, job_id))
    if not raw:
        return {"status": "not_found", "job_id": job_id}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "error", "job_id": job_id, "message": "Corrupted job state"}


def fetch_smc_backtest_job(user_id: int, job_id: str) -> dict[str, Any]:
    return fetch_desk_backtest_job(user_id, job_id)


def queue_smc_backtest_job(user_id: int, instrument_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Start SMC backtest without opening a DB connection."""
    job_id = uuid.uuid4().hex[:12]
    client = _redis_client()
    _write_desk_job(
        client,
        user_id,
        job_id,
        {
            "status": "queued",
            "kind": "smc",
            "progress": 0,
            "job_id": job_id,
            "instrument": instrument_key,
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    threading.Thread(
        target=_smc_backtest_worker,
        args=(user_id, instrument_key, job_id, payload),
        daemon=True,
        name=f"smc-backtest-{job_id}",
    ).start()
    return {"job_id": job_id, "status": "queued", "kind": "smc"}


def queue_desk_backtest_job(user_id: int, instrument_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Start adaptive desk backtest without opening a DB connection."""
    job_id = uuid.uuid4().hex[:12]
    client = _redis_client()
    _write_desk_job(
        client,
        user_id,
        job_id,
        {
            "status": "queued",
            "kind": "adaptive",
            "progress": 0,
            "job_id": job_id,
            "instrument": instrument_key,
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    threading.Thread(
        target=_desk_backtest_worker,
        args=(user_id, instrument_key, job_id, payload),
        daemon=True,
        name=f"desk-backtest-{job_id}",
    ).start()
    return {"job_id": job_id, "status": "queued", "kind": "adaptive"}


def _execute_smc_backtest_ctx(instrument_key: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """Run SMC pipeline without an open DB session."""
    meta = INSTRUMENTS[instrument_key]
    df: pd.DataFrame = ctx["df"]
    if df.empty:
        return {
            "status": "completed",
            "message": "No historical candles available",
            "ranking_table": [],
            "strategies": [],
            "load_notes": ctx.get("load_notes", []),
        }

    config = ctx["config"]
    smc_params = ctx.get("smc_params") or {}
    result = run_full_smc_pipeline(
        df,
        meta["lot_size"],
        float(config.get("capital", 100000)),
        instrument_key=instrument_key,
        optimize=bool(ctx.get("optimize")),
        max_loss_per_day=float(config.get("max_loss_per_day", 5000)),
        max_trades_per_day=int(config.get("max_trades_per_day", 8)),
        params=smc_params or None,
    )
    if smc_params and result.get("recommendation"):
        result["recommendation"]["smc_params"] = {**DEFAULT_SMC_PARAMS, **smc_params}
    result["data_source"] = ctx.get("data_source")
    result["bars_loaded"] = len(df)
    result["date_range"] = {"from": str(ctx["from_date"])[:10], "to": str(ctx["to_date"])[:10]}
    result["load_notes"] = ctx.get("load_notes", [])
    if smc_params:
        result["smc_params_used"] = smc_params
    if ctx.get("data_source") == "demo":
        result["warning"] = (
            "Backtest ran on synthetic demo data. Connect Angel One broker and retry for real NSE history."
        )
    return result


def _execute_desk_backtest_ctx(instrument_key: str, ctx: dict[str, Any]) -> dict[str, Any]:
    """Run adaptive backtest replay without an open DB session."""
    meta = INSTRUMENTS[instrument_key]
    df: pd.DataFrame = ctx["df"]
    config = ctx["config"]
    timeframe = ctx["timeframe"]
    strategy_code = ctx.get("strategy_code")
    if strategy_code:
        validate_strategy_code_for_engine("scalping", strategy_code)
    if df.empty:
        return {
            "status": "completed",
            "message": "No historical candles available",
            "total_trades": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "max_drawdown": 0,
            "equity_curve": [],
            "trades": [],
            "monthly_breakdown": [],
            "bars_loaded": 0,
            "strategy_code": strategy_code,
        }

    evaluation_days = ctx.get("evaluation_days")
    utilization_pct = float(
        config["capital_utilization_pct"]
        if config.get("capital_utilization_pct") is not None
        else 1.0
    )
    max_lots = int(config.get("backtest_max_lots") or 0)
    desk_params = dict(config.get("params") or {})
    smc_params = config.get("smc_params") or {}
    if smc_params:
        desk_params = {**desk_params, "smc_params": smc_params, **smc_params}
    common = dict(
        candles=df,
        timeframe=timeframe,
        lot_size=meta["lot_size"],
        capital=float(config.get("capital", 100000)),
        max_loss_per_day=float(config.get("max_loss_per_day", 5000)),
        max_trades_per_day=int(config.get("max_trades_per_day", 5)),
        instrument_key=instrument_key,
        params=desk_params,
        evaluation_days=evaluation_days,
        capital_utilization_pct=utilization_pct,
        max_lots_per_trade=max_lots,
    )
    if strategy_code:
        result = run_strategy_backtest(
            **common,
            strategy_code=strategy_code,
            ai_entry=bool(ctx.get("ai_entry")),
            ai_exit=bool(ctx.get("ai_exit")),
        )
    else:
        result = run_backtest(
            df,
            timeframe,
            meta["lot_size"],
            float(config.get("capital", 100000)),
            max_loss_per_day=float(config.get("max_loss_per_day", 5000)),
            max_trades_per_day=int(config.get("max_trades_per_day", 5)),
            instrument_key=instrument_key,
            strategy_mode=config.get("strategy_mode", "auto"),
            fixed_strategy_id=config.get("fixed_strategy_id"),
            strategy_family=config.get("strategy_family", "adaptive"),
            params=config.get("params"),
        )
    result["instrument"] = instrument_key
    result["bars_loaded"] = len(df)
    result["data_source"] = ctx.get("data_source")
    result["date_range"] = {
        "from": str(ctx.get("from_date", ""))[:10],
        "to": str(ctx.get("to_date", ""))[:10],
    }
    result["load_notes"] = ctx.get("load_notes") or []
    if ctx.get("data_source") == "angel_one":
        result["data_label"] = f"Angel One {timeframe} · up to {BACKTEST_MAX_DAYS} days"
    elif ctx.get("data_source") == "database":
        result["warning"] = (
            "Used cached database candles — Angel One live fetch was unavailable for this run."
        )
    if ctx.get("data_insufficient"):
        coverage = ctx.get("coverage_pct")
        expected = ctx.get("expected_bars")
        loaded = result.get("bars_loaded")
        sparse = (
            f"Only {loaded:,} bars loaded"
            + (f" (~{coverage}% of ~{expected:,} expected)" if coverage is not None and expected else "")
            + " — trade count will be much lower than a full 60-day Angel One run."
        )
        result["warning"] = f"{result.get('warning', '')} {sparse}".strip()
        result["data_insufficient"] = True
    if ctx.get("range_capped"):
        result["note"] = ctx.get("range_note")
    return result


def default_config(instrument_key: str) -> dict[str, Any]:
    meta = INSTRUMENTS[instrument_key]
    return {
        "capital": 100000,
        "max_loss_per_day": 5000,
        "max_trades_per_day": 3,
        "timeframe": "1m",
        "auto_trading_enabled": False,
        "lot_size": meta["lot_size"],
        "strategy_version": STRATEGY_VERSION,
        "strategy_label": STRATEGY_LABEL,
        "strategy_mode": "auto",
        "strategy_family": "battle",
        "fixed_strategy_id": "ema_crossover_rsi",
        "fixed_strategy_code": default_fixed_strategy_code(instrument_key),
        "catalog_version": CATALOG_VERSION,
        "strategy_settings": default_strategy_settings(instrument_key),
        "risk_per_trade_pct": 1.0,
        "max_daily_loss_pct": 5.0,
        # 0 = no lot cap — size from full deployable capital
        "max_lots_per_trade": 0,
        "auto_capital_from_broker": True,
        "capital_utilization_pct": 1.0,
        "expiry_restrictions_enabled": True,
        "smc_params": (
            dict(SMC_ORB_FVG_BANK_DEFAULTS)
            if instrument_key == "banknifty"
            else dict(SMC_ORB_FVG_NIFTY_DEFAULTS)
        ),
        "params": {
            **risk_profile(instrument_key),
            "volume_spike_ratio": 1.3,
            "rsi_call_min": 40,
            "rsi_call_max": 68,
            **(
                {
                    "orb_breakout": dict(ORB_BREAKOUT_BANK_DEFAULTS),
                    "ema_crossover": dict(EMA_CROSSOVER_BANK_DEFAULTS),
                }
                if instrument_key == "banknifty"
                else {
                    "orb_breakout": dict(ORB_BREAKOUT_NIFTY_DEFAULTS),
                    "vwap_bounce": dict(VWAP_BOUNCE_NIFTY_DEFAULTS),
                }
            ),
        },
    }


def _redis_keys(user_id: int, instrument_key: str) -> tuple[str, str]:
    base = f"{REDIS_DESK_PREFIX}:{user_id}:{instrument_key}"
    return f"{base}:config", f"{base}:state"


def _release_request_db(db: Session | None) -> None:
    """Return the FastAPI request session before long async/redis work."""
    if db is None:
        return
    try:
        db.rollback()
    except Exception:
        pass
    try:
        db.close()
    except Exception:
        pass


class ScalpingDeskService:
    def __init__(self, db: Session, user_id: int, instrument_key: str):
        if instrument_key not in INSTRUMENTS:
            raise ValueError(f"Unknown instrument: {instrument_key}")
        self.db = db
        self.user_id = user_id
        self.instrument_key = instrument_key
        self.meta = INSTRUMENTS[instrument_key]
        settings = get_settings()
        self.settings = settings
        self.redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        self.bus = MarketRedisBus(settings.REDIS_URL)
        self.scrip = ScripMasterService(self.redis)
        self.data_provider = StrategyDataProvider(self.bus, self.scrip)
        self.config_key, self.state_key = _redis_keys(user_id, instrument_key)

    def get_trading_mode(self) -> str:
        return TradingModeStore(self.settings.REDIS_URL).get(self.user_id)

    def resolve_execution_mode(self, strategy_mode: str) -> str:
        return "live"

    async def _fetch_broker_available_cash(self) -> float | None:
        config = self.get_config()
        if not config.get("auto_capital_from_broker", True):
            return None
        db = SessionLocal()
        try:
            manager = AngelOneSessionManager(db, self.redis)
            if not manager.get_connection_status(self.user_id).get("connected"):
                return None
            client = await manager.get_client_for_user(self.user_id)
            raw = await client.get_rms_limits()
            parsed = parse_rms_funds(raw)
            if not parsed.get("status"):
                return None
            cash = (parsed.get("data") or {}).get("availablecash")
            return float(cash) if cash not in (None, "") else None
        except (AngelOneAuthError, AngelOneAPIError, TypeError, ValueError):
            return None
        except Exception:
            logger.debug("Broker cash fetch failed for user=%s", self.user_id, exc_info=True)
            return None
        finally:
            db.close()

    def _sync_capital_context(
        self,
        state: dict[str, Any],
        config: dict[str, Any],
        *,
        broker_cash: float | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if not is_index_scalp_desk(self.instrument_key):
            return state, {}
        state, info = ensure_session_capital(state, config, broker_cash=broker_cash)
        self._save_state(state)
        return state, info

    def get_config(self) -> dict[str, Any]:
        raw = self.redis.get(self.config_key)
        if raw:
            try:
                cfg = json.loads(raw)
            except json.JSONDecodeError:
                cfg = default_config(self.instrument_key)
                self.save_config(cfg)
                return cfg
            if "min_profit_target_inr" in cfg:
                cfg.pop("min_profit_target_inr", None)
                self.save_config(cfg)
            prev_version = int(cfg.get("catalog_version") or 0)
            normalized = normalize_desk_config(cfg, self.instrument_key)
            if prev_version < int(normalized.get("catalog_version") or 0):
                self.save_config(normalized)
            return normalized
        cfg = default_config(self.instrument_key)
        self.save_config(cfg)
        return normalize_desk_config(cfg, self.instrument_key)

    def save_config(self, config: dict[str, Any]) -> dict[str, Any]:
        config.pop("min_profit_target_inr", None)
        config["lot_size"] = self.meta["lot_size"]
        normalized = normalize_desk_config(config, self.instrument_key)
        self.redis.setex(self.config_key, 86400 * 7, json.dumps(normalized))
        return normalized

    def get_state(self) -> dict[str, Any]:
        raw = self.redis.get(self.state_key)
        corrupted = False
        if raw:
            try:
                state = json.loads(raw)
            except json.JSONDecodeError:
                state = None
                corrupted = True
        else:
            state = None
        if state is None:
            state = {
                "signals": [],
                "active_trades": [],
                "trade_history": [],
                "daily_pnl": 0,
                "trades_today": 0,
                "wins_today": 0,
                "consecutive_wins": 0,
                "consecutive_losses": 0,
                "last_trade_at": None,
                "stream_connected": self._stream_connected(),
            }
        state = maybe_reset_daily_state(state)
        if not raw or corrupted:
            self._save_state(state)
        return state

    def _save_state(self, state: dict[str, Any]) -> None:
        self.redis.setex(self.state_key, 86400, json.dumps(state))

    def _resolve_option_lot_size(self, token: str | None = None) -> int:
        """Prefer Angel scrip-master lot for the contract; fall back to instrument default."""
        fallback = int(self.meta["lot_size"])
        if not token:
            return fallback
        try:
            inst = self.scrip.get_by_token(str(token))
            if inst and int(inst.lot_size or 0) > 0:
                return int(inst.lot_size)
        except Exception:
            logger.debug("Lot lookup failed for token=%s", token, exc_info=True)
        return fallback

    def _trade_lot_multiplier(self, trade: dict[str, Any]) -> int:
        return max(1, int(trade.get("lots") or 1))

    def _index_pnl(self, trade: dict[str, Any], spot: float, entry_spot: float) -> float:
        move = spot - entry_spot
        qty = self.meta["lot_size"] * self._trade_lot_multiplier(trade)
        pnl = move * qty
        if trade.get("signal_type") == "PUT":
            pnl = -pnl
        return pnl

    def _option_pnl(self, trade: dict[str, Any], exit_premium: float) -> float:
        entry = float(trade.get("entry") or 0)
        qty = self.meta["lot_size"] * self._trade_lot_multiplier(trade)
        return (float(exit_premium) - entry) * qty

    async def _resolve_option_mark_price(self, trade: dict[str, Any], spot: float) -> float:
        token = trade.get("option_token")
        if token:
            tick = self.bus.get_tick(2, str(token))
            if tick and tick.get("ltp"):
                return float(tick["ltp"])
        entry = float(trade.get("entry") or 0)
        entry_spot = float(trade.get("entry_spot") or trade.get("indicators", {}).get("spot") or spot)
        return estimate_option_mark_premium(entry, trade.get("signal_type"), entry_spot, spot)

    def _resolve_desk_lots(
        self,
        config: dict[str, Any],
        state: dict[str, Any],
        *,
        signal: dict[str, Any] | None = None,
        spot: float = 0,
        option_ltp: float = 100,
        capital_info: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if is_index_scalp_desk(self.instrument_key):
            if capital_info is None:
                _, capital_info = ensure_session_capital(state, config)
            deployable = float(capital_info.get("deployable_capital") or 0)
            premium = option_ltp
            if signal:
                ind = signal.get("indicators") or {}
                premium = float(
                    signal.get("entry")
                    or ind.get("option_ltp")
                    or ind.get("entry_premium")
                    or option_ltp
                    or 0
                )
            return compute_utilization_lots(
                self.instrument_key,
                deployable,
                premium,
                config=config,
                state=state,
            )

        if signal:
            targets = (signal.get("ai") or {}).get("targets")
            return size_from_signal_context(
                self.instrument_key,
                signal,
                state,
                config,
                targets,
                capital_info=capital_info,
            )
        stop_pts = float((config.get("params") or {}).get("stop_pts") or 7)
        if self.instrument_key == "banknifty":
            stop_pts = 72.0
        return compute_dynamic_position_size(
            instrument_key=self.instrument_key,
            capital=float(config.get("capital") or 100_000),
            open_pnl=float(state.get("daily_pnl") or 0),
            trade_count=int(state.get("trades_today") or 0),
            consecutive_losses=int(state.get("consecutive_losses") or 0),
            entry=option_ltp,
            stop_loss=max(option_ltp * 0.88, 1),
            config=config,
            risk_pts=stop_pts,
        )

    def _stream_connected(self) -> bool:
        status = self.bus.get_stream_status()
        return bool(status and status.get("connected"))

    async def fetch_candles(self, timeframe: str, bars: int = 120) -> list[dict[str, Any]]:
        """Fetch index OHLCV from Redis cache, DB, or Angel One REST."""
        cached = await self._fetch_redis_candles_only(timeframe, bars)
        if self._candles_look_valid(cached, min_bars=min(10, bars // 3)):
            return cached[-bars:]

        inst = self.scrip.index_token(self.meta["underlying"])
        if not inst:
            return cached

        df = await self._fetch_angel_candles(inst.token, timeframe)
        if df.empty:
            tick = self.bus.get_tick(1, inst.token)
            if tick:
                return self._tick_to_candles(tick, bars)
            return cached
        return df.to_dict(orient="records")

    async def _fetch_redis_candles_only(self, timeframe: str, bars: int = 120) -> list[dict[str, Any]]:
        """Fast path: latest Redis candle only (no history list in Redis)."""
        inst = self.scrip.index_token(self.meta["underlying"])
        if not inst:
            return []

        c = self.bus.get_candle(inst.token, timeframe)
        if c:
            return self._normalize_candles([c])

        tick = self.bus.get_tick(1, inst.token)
        if tick:
            return self._tick_to_candles(tick, min(bars, 40))
        return []

    @staticmethod
    def _candles_look_valid(candles: list[dict[str, Any]], *, min_bars: int = 10) -> bool:
        if len(candles) < min_bars:
            return False
        timestamps = [str(c.get("timestamp") or "") for c in candles]
        if len(set(timestamps)) < max(3, len(candles) // 4):
            return False
        valid_ohlc = 0
        for c in candles:
            o = float(c.get("open") or 0)
            h = float(c.get("high") or 0)
            l = float(c.get("low") or 0)
            cl = float(c.get("close") or 0)
            if cl > 0 and l > 0 and h >= l:
                valid_ohlc += 1
        return valid_ohlc >= min_bars

    async def _fetch_angel_candles(self, token: str, timeframe: str) -> pd.DataFrame:
        cooldown_key = f"angel:candle_cooldown:{self.user_id}:{token}:{timeframe}"
        if self.redis.get(cooldown_key):
            return pd.DataFrame()

        db = SessionLocal()
        try:
            manager = AngelOneSessionManager(db, self.redis)
            client = await manager.get_client_for_user(self.user_id)
            today = to_ist(None).date()
            from_date = (today - timedelta(days=5)).isoformat()
            to_date = today.isoformat()
            interval = LOADER_INTERVAL_MAP.get(timeframe, "ONE_MINUTE")
            window = angel_candle_window(from_date, to_date)
            if window is None:
                return pd.DataFrame()
            from_str, to_str = window
            response = await client.get_candles(
                CandleRequest(
                    exchange="NSE",
                    symboltoken=token,
                    interval=interval,
                    fromdate=from_str,
                    todate=to_str,
                )
            )
        except AngelOneAPIError as exc:
            if "rate limit" in str(exc).lower():
                self.redis.setex(cooldown_key, 300, "1")
            return pd.DataFrame()
        finally:
            db.close()
        candles = response.get("data") or []
        records = []
        for row in candles:
            if isinstance(row, (list, tuple)) and len(row) >= 6:
                records.append(
                    {
                        "timestamp": row[0],
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                    }
                )
        return pd.DataFrame(records)

    @staticmethod
    def _normalize_candles(rows: list[dict]) -> list[dict]:
        return [
            {
                "timestamp": r.get("candle_ts"),
                "open": r.get("open"),
                "high": r.get("high"),
                "low": r.get("low"),
                "close": r.get("close"),
                "volume": r.get("volume", 0),
            }
            for r in rows
        ]

    @staticmethod
    def _tick_to_candles(tick: dict, bars: int) -> list[dict]:
        ltp = float(tick.get("ltp") or 0)
        row = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "open": tick.get("open", ltp),
            "high": tick.get("high", ltp),
            "low": tick.get("low", ltp),
            "close": ltp,
            "volume": tick.get("volume", 0),
        }
        return [row] * min(bars, 40)

    async def get_desk_snapshot(self) -> dict[str, Any]:
        """Lightweight desk payload for polling — no strategy/AI evaluation or Angel REST."""
        config = self.get_config()
        state = self.get_state()
        state["stream_connected"] = self._stream_connected()
        broker_cash = await self._resolve_broker_cash(state, stream_cycle=True)
        state, capital_info = self._sync_capital_context(state, config, broker_cash=broker_cash)

        timeframe = config.get("timeframe", "1m")
        candles = await self._fetch_redis_candles_only(timeframe)

        inst = self.scrip.index_token(self.meta["underlying"])
        tick = self.bus.get_tick(1, inst.token) if inst else None
        spot = float(tick.get("ltp") if tick else (candles[-1]["close"] if candles else 0))

        chain = self.bus.get_option_chain(self.meta["underlying"]) or {"rows": {}}
        strikes = classify_strikes(chain, spot)

        strategy_selection = state.get("last_strategy_selection")
        market_ctx = state.get("last_market_context") or {}
        daily_stop = evaluate_ai_daily_stop(state, config, market_ctx)
        guards = guard_status(
            state, config, daily_stop=daily_stop, expiry_handler=state.get("last_expiry_handler")
        )

        active_trades = self._refresh_active_trades_spot(state.get("active_trades", []), spot)
        latest_signal = (state.get("signals") or [None])[0]

        atm_ce = strikes.get("atm_ce") or {}
        atm_pe = strikes.get("atm_pe") or {}
        option_ltp = float(atm_ce.get("ltp") or atm_pe.get("ltp") or 100)
        sizing = self._resolve_desk_lots(
            config,
            state,
            signal=latest_signal,
            option_ltp=option_ltp,
            capital_info=capital_info,
        )
        lots = int(sizing.get("lots") or 0)

        stream_status = self._build_stream_status(state, config)
        return {
            "instrument": self.instrument_key,
            "underlying": self.meta["underlying"],
            "label": self.meta["label"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "spot": spot,
            "spot_change_pct": self._spot_change(tick),
            "candles": candles[-80:],
            "strikes": strikes,
            "signal": latest_signal,
            "signals": state.get("signals", [])[:10],
            "active_trades": active_trades,
            "trade_history": state.get("trade_history", [])[-50:],
            "config": config,
            "execution_policy": SCALP_EXECUTION_POLICY,
            "option_execution_policy": config.get("option_execution_policy", "buy_only"),
            "guards": guards,
            "daily_summary": self._daily_summary(state),
            "daily_stop": daily_stop,
            "computed_lots": lots,
            "position_sizing": sizing,
            "strategy_version": STRATEGY_VERSION,
            "strategy_label": config.get("strategy_label") or STRATEGY_LABEL,
            "strategy_selection": strategy_selection,
            "market_regime": state.get("last_market_regime"),
            "mtf_context": state.get("last_mtf_context"),
            "orb_confirmation": state.get("last_orb_confirmation"),
            "expiry_handler": state.get("last_expiry_handler"),
            "eod_review": state.get("eod_review"),
            "weekly_tuning": state.get("weekly_tuning"),
            "pattern_memory": state.get("pattern_memory", [])[-10:],
            "last_pattern": state.get("last_pattern"),
            "last_loss_autopsy": state.get("last_loss_autopsy"),
            "loss_autopsies": state.get("loss_autopsies", [])[-5:],
            "last_win_reinforcement": state.get("last_win_reinforcement"),
            "win_reinforcements": state.get("win_reinforcements", [])[-5:],
            "available_strategies": filter_catalog_for_engine(
                "scalping", catalog_for_api(self.instrument_key, config)
            ),
            "strategy_catalog_version": CATALOG_VERSION,
            "desk": "scalping",
            "strategy_families": all_strategy_families(),
            "smc_dashboard": self._smc_dashboard(
                {**state, "active_trades": active_trades},
                strategy_selection,
                config,
            ),
            "trading_mode": self.get_trading_mode(),
            "capital_info": capital_info,
            "snapshot": True,
            "last_stream_eval_at": state.get("last_stream_eval_at"),
            "stream_status": stream_status,
            "last_live_entry_attempt": state.get("last_live_entry_attempt"),
            "last_live_entry_failure": state.get("last_live_entry_failure"),
        }

    def _refresh_active_trades_spot(self, active: list[dict], spot: float) -> list[dict]:
        if not active or not spot:
            return active
        updated = []
        for trade in active:
            entry_spot = float(trade.get("entry_spot") or trade.get("indicators", {}).get("spot") or spot)
            token = trade.get("option_token")
            option_ltp = None
            if token:
                tick = self.bus.get_tick(2, str(token))
                if tick and tick.get("ltp"):
                    option_ltp = float(tick["ltp"])
            if option_ltp is None:
                option_ltp = estimate_option_mark_premium(
                    float(trade.get("entry") or 0),
                    trade.get("signal_type"),
                    entry_spot,
                    spot,
                )
            pnl = self._option_pnl(trade, option_ltp)
            updated.append(
                {
                    **trade,
                    "current_ltp": round(option_ltp, 2),
                    "unrealized_pnl": round(pnl, 2),
                }
            )
        return updated

    @staticmethod
    def _apply_tick_to_stream_candles(candles: list[dict[str, Any]], tick: dict[str, Any]) -> list[dict[str, Any]]:
        """Update the forming bar or append a new 1m bar when the minute rolls."""
        ltp = float(tick.get("ltp") or 0)
        if ltp <= 0 or not candles:
            return candles
        now_bucket = datetime.now(IST).replace(second=0, microsecond=0)
        last = dict(candles[-1])
        last_dt = pd.to_datetime(last.get("timestamp"), errors="coerce")
        if pd.isna(last_dt):
            last_bucket = now_bucket
        else:
            if last_dt.tzinfo is None:
                last_dt = last_dt.tz_localize(IST)
            else:
                last_dt = last_dt.tz_convert(IST)
            last_bucket = last_dt.to_pydatetime().replace(second=0, microsecond=0)

        if now_bucket > last_bucket:
            candles = candles + [
                {
                    "timestamp": now_bucket.isoformat(),
                    "open": ltp,
                    "high": ltp,
                    "low": ltp,
                    "close": ltp,
                    "volume": float(tick.get("volume") or 0),
                }
            ]
        else:
            prev_high = float(last.get("high") or 0)
            prev_low = float(last.get("low") or 0)
            last["close"] = ltp
            last["high"] = max(prev_high if prev_high > 0 else ltp, ltp)
            last["low"] = min(prev_low if prev_low > 0 else ltp, ltp)
            if float(last.get("open") or 0) <= 0:
                last["open"] = ltp
            candles = candles[:-1] + [last]
        return candles

    async def _fetch_stream_candles(
        self,
        timeframe: str,
        state: dict[str, Any],
        *,
        bars: int = 120,
    ) -> list[dict[str, Any]]:
        """Fast path for 1s stream cycles — cache history, refresh last bar from live tick."""
        refresh_sec = int(getattr(self.settings, "SCALPING_CANDLE_CACHE_SEC", 30))
        cached = state.get("_stream_candles_cache")
        cached_at = state.get("_stream_candles_at")
        use_cache = False
        if cached and cached_at:
            try:
                ts = datetime.fromisoformat(str(cached_at))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                use_cache = datetime.now(timezone.utc) - ts < timedelta(seconds=refresh_sec)
            except ValueError:
                use_cache = False

        candles = list(cached) if use_cache and isinstance(cached, list) and self._candles_look_valid(cached) else await self.fetch_candles(timeframe, bars)
        if not self._candles_look_valid(candles):
            candles = await self.fetch_candles(timeframe, bars)
        if not candles:
            candles = await self._fetch_redis_candles_only(timeframe, bars)

        inst = self.scrip.index_token(self.meta["underlying"])
        tick = self.bus.get_tick(1, inst.token) if inst else None
        if tick and candles:
            candles = self._apply_tick_to_stream_candles(candles, tick)
        elif tick and not candles:
            candles = self._tick_to_candles(tick, min(bars, 40))

        state["_stream_candles_cache"] = candles[-bars:]
        state["_stream_candles_at"] = datetime.now(timezone.utc).isoformat()
        return candles

    async def _resolve_broker_cash(
        self,
        state: dict[str, Any],
        *,
        stream_cycle: bool,
    ) -> float | None:
        refresh_sec = int(getattr(self.settings, "SCALPING_BROKER_CASH_REFRESH_SEC", 60))
        if stream_cycle:
            cached_at = state.get("broker_cash_fetched_at")
            cached_cash = state.get("broker_cash_cached")
            if cached_at is not None and cached_cash is not None:
                try:
                    ts = datetime.fromisoformat(str(cached_at))
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    if datetime.now(timezone.utc) - ts < timedelta(seconds=refresh_sec):
                        return float(cached_cash)
                except (ValueError, TypeError):
                    pass
        cash = await self._fetch_broker_available_cash()
        if cash is not None:
            state["broker_cash_cached"] = cash
            state["broker_cash_fetched_at"] = datetime.now(timezone.utc).isoformat()
        return cash

    async def evaluate_desk(self, *, stream_cycle: bool = False) -> dict[str, Any]:
        """Run full desk evaluation cycle."""
        config = self.get_config()
        state = self.get_state()
        state["stream_connected"] = self._stream_connected()
        state = await self._hydrate_live_open_trades(state)
        broker_cash = await self._resolve_broker_cash(state, stream_cycle=stream_cycle)
        state, capital_info = self._sync_capital_context(state, config, broker_cash=broker_cash)

        timeframe = config.get("timeframe", "1m")
        if stream_cycle:
            candles = await self._fetch_stream_candles(timeframe, state)
        else:
            candles = await self.fetch_candles(timeframe)
        df = pd.DataFrame(candles) if candles else pd.DataFrame()

        inst = self.scrip.index_token(self.meta["underlying"])
        tick = self.bus.get_tick(1, inst.token) if inst else None
        spot = float(tick.get("ltp") if tick else (df.iloc[-1]["close"] if len(df) else 0))

        chain = self.bus.get_option_chain(self.meta["underlying"]) or {"rows": {}}
        strikes = classify_strikes(chain, spot)

        strategy_selection = None
        signal_obj = None
        if len(df) >= 21:
            signal_obj, strategy_selection = select_from_catalog(
                df,
                timeframe,
                chain,
                self.meta["lot_size"],
                self.instrument_key,
                config,
                tick=tick,
                underlying=self.meta["underlying"],
                params=config.get("params"),
            )

        market_ctx = (strategy_selection or {}).get("market_context") or {}
        if not market_ctx and len(df) >= 5:
            market_ctx = build_market_context(
                df,
                tick=tick,
                chain=chain,
                underlying=self.meta["underlying"],
                instrument_key=self.instrument_key,
                mtf_context=mtf_context,
                macro_inputs=macro_inputs,
            )
        macro_inputs = config.get("macro_inputs") or state.get("macro_inputs") or {}
        market_regime = classify_from_market_context(
            instrument_key=self.instrument_key,
            market_ctx=market_ctx,
            macro_inputs=macro_inputs,
            is_expiry=is_instrument_expiry_day(None, self.instrument_key),
        )
        market_ctx = merge_regime_into_context(market_ctx, market_regime)
        mtf_context = build_mtf_analysis(df, spot=spot) if len(df) >= 30 else {}
        if mtf_context:
            market_ctx = merge_mtf_into_context(market_ctx, mtf_context)
        trend_dir = (mtf_context or {}).get("trend_1h") or market_ctx.get("direction")
        expiry_handler = handle_expiry_day(
            self.instrument_key,
            macro=macro_inputs,
            default_max_trades=(
                3 if config.get("max_trades_per_day") is None else int(config.get("max_trades_per_day"))
            ),
            trend_direction=trend_dir,
        )
        expiry_handler = apply_expiry_restriction_toggle(
            expiry_handler,
            enabled=bool(config.get("expiry_restrictions_enabled", True)),
            default_max_trades=(
                3 if config.get("max_trades_per_day") is None else int(config.get("max_trades_per_day"))
            ),
        )
        orb_confirmation = confirm_orb_from_df(
            self.instrument_key,
            df,
            spot=spot,
            tick=tick,
            macro={**(macro_inputs or {}), **(market_regime or {})},
        )
        if strategy_selection is not None:
            strategy_selection = {**strategy_selection, "market_context": market_ctx, "regime": market_ctx.get("regime")}
            strategy_selection["market_regime"] = market_regime
            strategy_selection["mtf_context"] = mtf_context
            strategy_selection["orb_confirmation"] = orb_confirmation
            strategy_selection["expiry_handler"] = expiry_handler
        elif market_ctx:
            strategy_selection = {
                "market_context": market_ctx,
                "regime": market_ctx.get("regime"),
                "market_regime": market_regime,
                "mtf_context": mtf_context,
                "orb_confirmation": orb_confirmation,
                "expiry_handler": expiry_handler,
            }

        daily_stop = evaluate_ai_daily_stop(state, config, market_ctx)
        if daily_stop.get("stop_trading"):
            state = apply_daily_stop(state, daily_stop)
            self._save_state(state)

        guards = guard_status(state, config, daily_stop=daily_stop, expiry_handler=expiry_handler)
        signal = None
        ai_decision = None
        can_evaluate = len(df) >= 21 and (
            guards["can_enter"]
            or guards.get("can_enter_paper")
            or not config.get("auto_trading_enabled")
        )

        if signal_obj and can_evaluate:
            signal = ensure_buy_only_signal(signal_obj.to_dict())
            selection = strategy_selection or {}
            context = {
                "underlying": self.meta["underlying"],
                "recent_candles": candles[-10:],
                "market_context": selection.get("market_context") or {},
                "strategy_selection": selection,
                "capital": capital_info.get("deployable_capital") or config.get("capital"),
                "capital_info": capital_info,
                "lot_size": self.meta["lot_size"],
                "current_pnl": state.get("daily_pnl", 0),
                "trades_today": state.get("trades_today", 0),
                "consecutive_losses": state.get("consecutive_losses", 0),
                "active_trades": state.get("active_trades", []),
                "max_loss_per_day": config.get("max_loss_per_day"),
                "max_trades_per_day": config.get("max_trades_per_day"),
                "max_daily_loss_pct": config.get("max_daily_loss_pct"),
                "risk_per_trade_pct": config.get("risk_per_trade_pct"),
                "max_lots_per_trade": config.get("max_lots_per_trade", 0),
                "capital_utilization_pct": config.get("capital_utilization_pct", 1.0),
                "data_provider": self.data_provider,
                "market_regime": market_regime,
                "mtf_context": mtf_context,
                "orb_confirmation": orb_confirmation,
                "expiry_handler": expiry_handler,
            }
            ai_decision = evaluate_ai_decision(self.instrument_key, signal, context)
            if ai_decision.get("targets"):
                apply_ai_targets(signal, ai_decision["targets"])
            signal["ai"] = ai_decision
            signal["strategy_selection"] = selection
            sizing = ai_decision.get("position_size") or {}
            signal["lots"] = int(ai_decision.get("lots") or sizing.get("lots") or 0)
            signal["position_sizing"] = sizing
            signal["entry_validation"] = ai_decision.get("entry_validation")
            signal["orb_confirmation"] = orb_confirmation or ai_decision.get("orb_confirmation")
            strategy_id = signal.get("strategy_id") or (signal.get("indicators") or {}).get("strategy_id")
            orb_ok = True
            # SMC ORB+FVG already applies smc_orb_* range/bias filters; battle ORB uses confirm_orb.
            if strategy_id == "orb_breakout":
                orb_ok = orb_confirmation_allows_entry(signal.get("orb_confirmation"), signal.get("signal_type"))
            expiry_ok = expiry_allows_signal(
                expiry_handler,
                signal.get("signal_type"),
                trend_direction=trend_dir,
            )
            strategy_id = signal.get("strategy_id") or (signal.get("indicators") or {}).get("strategy_id") or ""
            is_battle = (
                strategy_id in ("ema_crossover_rsi", "orb_breakout", "vwap_bounce", "momentum_burst", "trend_follow", "volume_breakout")
                or str(config.get("strategy_family") or "").lower() == "battle"
            )
            is_smc = strategy_id.startswith("smc_") or str(config.get("strategy_family") or "").lower() == "smc"
            from trading_shared.strategies.scalping_desk.adaptive_session import mtf_aligns_with_signal

            mtf_ok = mtf_aligns_with_signal(
                mtf_context, signal.get("signal_type"), strategy_id=strategy_id
            )
            validation_verdict = ai_decision.get("validation_verdict")
            if validation_verdict == "SKIP":
                validation_ok = False
            elif validation_verdict == "TAKE":
                validation_ok = True
            elif (is_battle or is_smc) and ai_decision["action"] == "ENTER":
                validation_ok = True
            else:
                validation_ok = verdict_allows_entry(ai_decision.get("entry_validation"))
            approved = (
                ai_decision["action"] == "ENTER"
                and ai_decision["confidence"] >= AI_CONFIDENCE_ENTER
                and sizing.get("action") != "HALT"
                and signal["lots"] > 0
                and validation_ok
                and mtf_ok
                and orb_ok
                and expiry_ok
            )
            signal["expiry_handler"] = expiry_handler
            skip_reasons: list[str] = []
            if ai_decision.get("action") != "ENTER":
                skip_reasons.append(f"ai_{ai_decision.get('action')}")
            elif float(ai_decision.get("confidence") or 0) < AI_CONFIDENCE_ENTER:
                skip_reasons.append(f"ai_confidence_{ai_decision.get('confidence')}")
            if sizing.get("action") == "HALT" or int(signal.get("lots") or 0) <= 0:
                skip_reasons.append(str(sizing.get("reason") or "lots_zero"))
            if not validation_ok:
                skip_reasons.append(f"validation_{validation_verdict or 'fail'}")
            if not mtf_ok:
                skip_reasons.append("mtf_15m_not_aligned")
            if not orb_ok:
                skip_reasons.append("orb_not_confirmed")
            if not expiry_ok:
                skip_reasons.append("expiry_block")
            signal["skip_reasons"] = skip_reasons
            signal["status"] = "approved" if approved else "skipped"
            memory = load_pattern_memory(self.redis, self.user_id, self.instrument_key)
            signal["pattern_match"] = match_signal_to_memory(
                signal,
                memory,
                regime=str(market_regime.get("regime") or market_regime.get("scalp_regime") or ""),
            )
            self._log_signal_event(state, signal)

            if signal["status"] == "approved":
                state["signals"] = ([signal] + state.get("signals", []))[:20]
                code = resolve_strategy_code(
                    selection=strategy_selection,
                    signal=signal,
                    config=config,
                    instrument_key=self.instrument_key,
                )
                if code:
                    setting = strategy_setting(config, code, self.instrument_key)
                    strategy_mode = str(config.get("strategy_mode") or "auto").lower()
                    # Auto monitors the full catalog; manual only places for checkbox-enabled codes.
                    allow_entry = bool(setting.get("enabled")) or strategy_mode == "auto"
                    if allow_entry:
                        if guards.get("can_enter"):
                            try:
                                entry = await self.enter_trade_from_signal(
                                    signal, config, execution_mode="live", strategy_code=code, state=state
                                )
                            except Exception as exc:
                                logger.exception(
                                    "Scalping live entry raised instrument=%s strategy=%s",
                                    self.instrument_key,
                                    code,
                                )
                                entry = {
                                    "ok": False,
                                    "reason": [str(exc)],
                                    "error_type": type(exc).__name__,
                                }
                            entry_meta = self._record_live_entry_result(
                                state,
                                signal,
                                entry,
                                strategy_code=code,
                                execution_mode="live",
                            )
                            if not entry_meta.get("ok"):
                                logger.warning(
                                    "Scalping live entry failed instrument=%s strategy=%s reason=%s",
                                    self.instrument_key,
                                    code,
                                    entry_meta.get("reason"),
                                )
                            self._log_signal_event(state, signal)

        state["active_trades"] = await self._update_active_trades(
            state.get("active_trades", []),
            df,
            config,
            force_exit=bool(guards.get("force_exit")),
            desk_state=state,
        )
        if strategy_selection:
            state["last_strategy_selection"] = strategy_selection
        if market_ctx:
            state["last_market_context"] = market_ctx
        if market_regime:
            state["last_market_regime"] = market_regime
        if mtf_context:
            state["last_mtf_context"] = mtf_context
        if orb_confirmation:
            state["last_orb_confirmation"] = orb_confirmation
        if expiry_handler:
            state["last_expiry_handler"] = expiry_handler
        eod_review = self._maybe_auto_eod_review(state, config)
        if stream_cycle:
            self._record_stream_eval(state)
        stream_status = self._build_stream_status(state, config)
        state["last_stream_status"] = stream_status
        self._save_state(state)

        atm_ce = strikes.get("atm_ce") or {}
        atm_pe = strikes.get("atm_pe") or {}
        option_ltp = float(atm_ce.get("ltp") or atm_pe.get("ltp") or 100)
        sizing = self._resolve_desk_lots(
            config,
            state,
            signal=signal,
            option_ltp=option_ltp,
            capital_info=capital_info,
        )
        lots = int((signal or {}).get("lots") or sizing.get("lots") or 0)

        return {
            "instrument": self.instrument_key,
            "underlying": self.meta["underlying"],
            "label": self.meta["label"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "spot": spot,
            "spot_change_pct": self._spot_change(tick),
            "candles": candles[-80:],
            "strikes": strikes,
            "signal": signal,
            "signals": state.get("signals", [])[:10],
            "active_trades": state.get("active_trades", []),
            "trade_history": state.get("trade_history", [])[-50:],
            "config": config,
            "execution_policy": SCALP_EXECUTION_POLICY,
            "option_execution_policy": config.get("option_execution_policy", "buy_only"),
            "guards": guards,
            "daily_summary": self._daily_summary(state),
            "daily_stop": daily_stop,
            "computed_lots": lots,
            "position_sizing": sizing,
            "strategy_version": STRATEGY_VERSION,
            "strategy_label": STRATEGY_LABEL,
            "strategy_selection": strategy_selection,
            "market_regime": market_regime,
            "mtf_context": mtf_context,
            "orb_confirmation": orb_confirmation,
            "expiry_handler": expiry_handler,
            "eod_review": eod_review,
            "weekly_tuning": state.get("weekly_tuning"),
            "pattern_memory": state.get("pattern_memory", [])[-10:],
            "last_pattern": state.get("last_pattern"),
            "last_loss_autopsy": state.get("last_loss_autopsy"),
            "loss_autopsies": state.get("loss_autopsies", [])[-5:],
            "last_win_reinforcement": state.get("last_win_reinforcement"),
            "win_reinforcements": state.get("win_reinforcements", [])[-5:],
            "available_strategies": filter_catalog_for_engine(
                "scalping", catalog_for_api(self.instrument_key, config)
            ),
            "strategy_catalog_version": CATALOG_VERSION,
            "desk": "scalping",
            "strategy_families": all_strategy_families(),
            "smc_dashboard": self._smc_dashboard(state, strategy_selection, config),
            "trading_mode": self.get_trading_mode(),
            "capital_info": capital_info,
            "snapshot": False,
            "stream_cycle": stream_cycle,
            "last_stream_eval_at": state.get("last_stream_eval_at"),
            "stream_status": stream_status,
            "last_live_entry_attempt": state.get("last_live_entry_attempt"),
            "last_live_entry_failure": state.get("last_live_entry_failure"),
        }

    def _age_seconds(self, iso: str | None) -> float | None:
        if not iso:
            return None
        try:
            ts = datetime.fromisoformat(str(iso))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
        except ValueError:
            return None

    def _record_stream_eval(self, state: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        cutoff = now - timedelta(seconds=120)
        history: list[str] = []
        for raw in state.get("stream_eval_history") or []:
            try:
                ts = datetime.fromisoformat(str(raw))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    history.append(str(raw))
            except ValueError:
                continue
        history.append(now_iso)
        state["stream_eval_history"] = history[-120:]
        state["last_stream_eval_at"] = now_iso

    @staticmethod
    def _normalize_reason_list(reason: Any) -> list[str]:
        if reason is None:
            return []
        if isinstance(reason, list):
            return [str(item) for item in reason if str(item or "").strip()]
        text = str(reason).strip()
        return [text] if text else []

    def _record_live_entry_result(
        self,
        state: dict[str, Any],
        signal: dict[str, Any],
        result: dict[str, Any] | None,
        *,
        strategy_code: str | None,
        execution_mode: str = "live",
    ) -> dict[str, Any]:
        entry_result = dict(result or {})
        reasons = self._normalize_reason_list(entry_result.get("reason"))
        now_iso = datetime.now(timezone.utc).isoformat()
        entry_meta = {
            "ok": bool(entry_result.get("ok")),
            "execution_mode": execution_mode,
            "strategy_code": strategy_code,
            "at": now_iso,
            "reason": reasons,
        }
        if entry_result.get("trade"):
            entry_meta["trade"] = entry_result["trade"]
        if entry_result.get("order_id"):
            entry_meta["order_id"] = entry_result.get("order_id")
        if entry_result.get("order_ids"):
            entry_meta["order_ids"] = entry_result.get("order_ids")
        if entry_result.get("error_type"):
            entry_meta["error_type"] = entry_result.get("error_type")
        signal["trade_entry"] = entry_meta
        state["last_live_entry_attempt"] = {
            "signal_timestamp": signal.get("timestamp"),
            "signal_type": signal.get("signal_type"),
            "strategy_id": signal.get("strategy_id"),
            **entry_meta,
        }
        if entry_meta["ok"]:
            state["last_live_entry_failure"] = None
        else:
            state["last_live_entry_failure"] = {
                "signal_timestamp": signal.get("timestamp"),
                "signal_type": signal.get("signal_type"),
                "strategy_id": signal.get("strategy_id"),
                "option_symbol": signal.get("option_symbol"),
                "option_token": signal.get("option_token"),
                "entry": signal.get("entry"),
                "lots": signal.get("lots"),
                **entry_meta,
            }
        return entry_meta

    def _evals_per_minute(self, state: dict[str, Any]) -> int:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=60)
        count = 0
        for raw in state.get("stream_eval_history") or []:
            try:
                ts = datetime.fromisoformat(str(raw))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    count += 1
            except ValueError:
                continue
        return count

    def _read_stream_worker_heartbeat(self) -> dict[str, Any]:
        raw = self.redis.get(REDIS_STREAM_WORKER_HEARTBEAT)
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def _build_stream_status(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        stream = self.bus.get_stream_status() or {}
        inst = self.scrip.index_token(self.meta["underlying"])
        tick = self.bus.get_tick(1, inst.token) if inst else None
        last_tick_at = stream.get("last_tick_at")
        last_eval = state.get("last_stream_eval_at")
        eval_age = self._age_seconds(last_eval)
        tick_age = self._age_seconds(last_tick_at)
        interval = max(float(getattr(self.settings, "SCALPING_STREAM_INTERVAL_SEC", 1.0)), 0.5)
        market_connected = bool(stream.get("connected"))
        desk_connected = bool(state.get("stream_connected"))
        auto_on = bool(config.get("auto_trading_enabled"))
        heartbeat = self._read_stream_worker_heartbeat()
        hb_age = self._age_seconds(heartbeat.get("at"))
        worker_alive = hb_age is not None and hb_age <= 15
        market_session_open = bool(heartbeat.get("market_session")) if heartbeat else None
        enabled_desks = max(1, int(heartbeat.get("enabled_desks") or 1))
        # Each evaluate_desk cycle fetches Angel LTP/options and can take several seconds.
        # With multiple auto desks the runner loop is serialized per interval, so allow a
        # generous stall window instead of treating normal API latency as "stalled".
        stall_threshold_sec = max(20.0, interval * enabled_desks * 10)
        expected_cycle_sec = max(interval + 4.0 * enabled_desks, interval * 2)
        eval_recent = eval_age is not None and eval_age <= stall_threshold_sec
        if auto_on and worker_alive and market_session_open is False:
            worker_active = True
            worker_phase = "idle_market_closed"
        elif auto_on and worker_alive and market_session_open and eval_recent:
            worker_active = True
            worker_phase = "running"
        elif auto_on and worker_alive and market_session_open and not eval_recent:
            worker_active = False
            worker_phase = "stalled"
        elif worker_alive:
            worker_active = not auto_on or eval_recent or market_session_open is False
            worker_phase = "idle" if not auto_on else ("running" if eval_recent else "idle_market_closed")
        else:
            worker_active = False
            worker_phase = "offline"
        return {
            "instrument": self.instrument_key,
            "underlying": self.meta["underlying"],
            "market_stream_connected": market_connected,
            "desk_stream_connected": desk_connected,
            "stream_ready": market_connected and desk_connected,
            "stream_worker_alive": worker_alive,
            "stream_worker_active": worker_active,
            "stream_worker_phase": worker_phase,
            "market_session_open": market_session_open,
            "auto_trading_enabled": auto_on,
            "enabled_desks": int(heartbeat.get("enabled_desks") or 0),
            "stream_worker_heartbeat_at": heartbeat.get("at"),
            "stream_worker_heartbeat_age_sec": round(hb_age, 1) if hb_age is not None else None,
            "stream_worker_stale": bool(auto_on and (hb_age is None or hb_age > stall_threshold_sec)),
            "last_tick_at": last_tick_at,
            "tick_age_sec": round(tick_age, 1) if tick_age is not None else None,
            "last_stream_eval_at": last_eval,
            "eval_age_sec": round(eval_age, 1) if eval_age is not None else None,
            "evals_per_minute": self._evals_per_minute(state),
            "target_evals_per_minute": max(1, int(round(60 / expected_cycle_sec))),
            "eval_stall_threshold_sec": round(stall_threshold_sec, 1),
            "stream_interval_sec": interval,
            "ticks_received": int(stream.get("ticks_received") or 0),
            "spot_ltp": float(tick.get("ltp") or 0) if tick else None,
        }

    def _spot_change(self, tick: dict | None) -> float:
        if not tick:
            return 0.0
        prev = float(tick.get("close") or tick.get("open") or tick.get("ltp") or 0)
        ltp = float(tick.get("ltp") or 0)
        return round((ltp - prev) / prev * 100, 2) if prev else 0.0

    async def _update_active_trades(
        self,
        active: list[dict],
        df: pd.DataFrame,
        config: dict,
        *,
        force_exit: bool = False,
        desk_state: dict | None = None,
    ) -> list[dict]:
        if not active:
            return active
        data = enrich_candles(df) if df is not None and not df.empty else pd.DataFrame()
        row = data.iloc[-1] if not data.empty else {}
        spot = float(row["close"]) if not data.empty else 0.0
        updated = []
        state = desk_state if desk_state is not None else self.get_state()

        for trade in active:
            entry_spot = float(trade.get("entry_spot") or trade.get("indicators", {}).get("spot") or spot)
            stop_pts = float(trade.get("stop_pts") or trade.get("indicators", {}).get("index_stop_pts") or 0)
            target_pts = float(trade.get("target_pts") or trade.get("indicators", {}).get("index_target_pts") or 0)
            hold_limit = int(trade.get("max_hold_bars") or trade.get("indicators", {}).get("max_hold_bars") or max_hold_bars(self.instrument_key))
            bars_held = _entry_bars_held(trade, candle_count=len(data))

            if not stop_pts or not target_pts:
                atr = float(trade.get("indicators", {}).get("atr") or entry_spot * 0.002)
                stop_pts, target_pts = compute_scalp_risk(entry_spot, atr, self.instrument_key)

            entry_premium = float(trade.get("entry") or 0)
            if entry_premium > 0:
                sl_px, tgt_px = normalize_long_premium_levels(
                    entry_premium,
                    float(trade.get("target") or 0),
                    float(trade.get("stoploss") or 0),
                )
                trade["stoploss"] = sl_px
                trade["target"] = tgt_px

            trailing = {"action": "HOLD"}
            if not data.empty and spot > 0:
                trailing = manage_trailing_sl(
                    instrument_key=self.instrument_key,
                    trade=trade,
                    current_price=spot,
                    df=data,
                )
                trade = apply_trailing_to_trade(trade, trailing)
            stop_pts = float(trade.get("stop_pts") or stop_pts)
            trail_floor = trade.get("trail_floor_move")

            ai_exit = {"action": "HOLD", "confidence": 0}
            if not data.empty and spot > 0:
                ai_exit = evaluate_ai_exit(
                    trade, spot, bars_held, trailing=trailing, df=data, vwap=float(row.get("vwap") or spot)
                )
            option_ltp = await self._resolve_option_mark_price(trade, spot)
            if _entered_this_cycle(trade) and not force_exit:
                unrealized = self._option_pnl(trade, option_ltp)
                trade["current_ltp"] = round(option_ltp, 2)
                trade["unrealized_pnl"] = round(unrealized, 2)
                updated.append(trade)
                continue
            exit_hit, reason = should_exit(
                trade["signal_type"],
                option_ltp,
                entry_premium,
                float(trade.get("target") or entry_premium * 1.08),
                float(trade.get("stoploss") or entry_premium * 0.88),
                trade.get("indicators") or {},
            )
            if not exit_hit and spot > 0:
                exit_hit, reason = should_exit_index(
                    trade["signal_type"],
                    spot,
                    entry_spot,
                    target_pts,
                    stop_pts,
                    bars_held=bars_held,
                    max_hold=hold_limit,
                    trail_floor_move=float(trail_floor) if trail_floor is not None else None,
                )
            if trailing.get("action") == "EXIT":
                exit_hit = True
                reason = trailing.get("reason") or "trail_stop"
            elif ai_exit.get("action") == "EXIT" and float(ai_exit.get("confidence") or 0) >= AI_CONFIDENCE_ENTER:
                exit_hit = True
                reason = ai_exit.get("mode") or "ai_quick_exit"
            if force_exit:
                exit_hit = True
                reason = reason or "market_close"
            if exit_hit:
                logger.info(
                    "Scalping auto-exit instrument=%s symbol=%s reason=%s ltp=%s entry=%s sl=%s tgt=%s",
                    self.instrument_key,
                    trade.get("option_symbol"),
                    reason,
                    option_ltp,
                    entry_premium,
                    trade.get("stoploss"),
                    trade.get("target"),
                )

            if exit_hit:
                closed_ok = False
                try:
                    closed_ok = await self._close_scalping_option_position(
                        trade,
                        exit_premium=option_ltp,
                        reason=reason or "exit",
                    )
                except Exception:
                    logger.exception("Option close failed for scalping order %s", trade.get("order_id"))

                if not closed_ok:
                    trade["bars_held"] = bars_held
                    trade["current_ltp"] = round(option_ltp, 2)
                    trade["unrealized_pnl"] = round(self._option_pnl(trade, option_ltp), 2)
                    updated.append(trade)
                    continue

                pnl = self._option_pnl(trade, option_ltp)
                closed = {
                    **trade,
                    "exit": round(option_ltp, 2),
                    "exit_premium": round(option_ltp, 2),
                    "pnl": round(pnl, 2),
                    "exit_reason": reason,
                    "status": "closed",
                    "ai_exit": ai_exit,
                }
                state["trade_history"] = (state.get("trade_history", []) + [closed])[-100:]
                state["daily_pnl"] = round(float(state.get("daily_pnl", 0)) + pnl, 2)
                state["trades_today"] = int(state.get("trades_today", 0)) + 1
                if pnl > 0:
                    state["wins_today"] = int(state.get("wins_today", 0)) + 1
                record_trade_result(state, pnl)
                regime = str(
                    (state.get("last_market_regime") or {}).get("regime")
                    or (state.get("last_market_regime") or {}).get("scalp_regime")
                    or "UNKNOWN"
                )
                history = load_pattern_memory(self.redis, self.user_id, self.instrument_key)
                pattern = log_trade_pattern(
                    instrument_key=self.instrument_key,
                    trade=closed,
                    regime=regime,
                    history=history,
                )
                save_pattern_memory(self.redis, self.user_id, self.instrument_key, pattern)
                state["pattern_memory"] = (state.get("pattern_memory", []) + [pattern])[-50:]
                state["last_pattern"] = pattern
                if pnl <= 0:
                    autopsy = autopsy_losing_trade(
                        instrument_key=self.instrument_key,
                        trade=closed,
                        regime=regime,
                        df=data,
                        market_regime=state.get("last_market_regime"),
                    )
                    save_loss_autopsy(self.redis, self.user_id, self.instrument_key, autopsy)
                    state["loss_autopsies"] = (state.get("loss_autopsies", []) + [autopsy])[-30:]
                    state["last_loss_autopsy"] = autopsy
                else:
                    reinforcement = reinforce_winning_trade(
                        instrument_key=self.instrument_key,
                        trade=closed,
                        regime=regime,
                        df=data,
                    )
                    save_win_reinforcement(self.redis, self.user_id, self.instrument_key, reinforcement)
                    state["win_reinforcements"] = (state.get("win_reinforcements", []) + [reinforcement])[-30:]
                    state["last_win_reinforcement"] = reinforcement
                config = self.get_config()
                ind = closed.get("indicators") or {}
                market_ctx = {
                    "volume_ratio": float(ind.get("volume_ratio") or 1),
                    "regime": "RANGING",
                    "trend_strength": 0,
                }
                stop_decision = evaluate_ai_daily_stop(state, config, market_ctx)
                apply_daily_stop(state, stop_decision)
            else:
                unrealized = self._option_pnl(trade, option_ltp)
                trade["current_ltp"] = round(option_ltp, 2)
                trade["entry_spot"] = entry_spot
                trade["stop_pts"] = stop_pts
                trade["target_pts"] = target_pts
                trade["max_hold_bars"] = hold_limit
                trade["bars_held"] = bars_held
                trade["ai_exit"] = ai_exit
                trade["trailing_sl"] = trailing
                trade["unrealized_pnl"] = round(unrealized, 2)
                updated.append(trade)

        state["active_trades"] = updated
        self._save_state(state)
        return updated

    def _daily_summary(self, state: dict) -> dict:
        trades = int(state.get("trades_today") or 0)
        wins = int(state.get("wins_today") or 0)
        return {
            "total_pnl": round(float(state.get("daily_pnl") or 0), 2),
            "trades": trades,
            "win_rate": round(wins / trades * 100, 1) if trades else 0,
            "wins": wins,
            "consecutive_wins": int(state.get("consecutive_wins") or 0),
            "ai_stopped": bool(state.get("ai_daily_stop")),
        }

    def _log_signal_event(self, state: dict[str, Any], signal: dict[str, Any]) -> None:
        today = trading_day_key()
        log = state.setdefault("signal_log", [])
        trade_entry = signal.get("trade_entry") or {}
        event = {
            "day": today,
            "status": signal.get("status"),
            "timestamp": signal.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "strategy_id": signal.get("strategy_id"),
            "skip_reasons": signal.get("skip_reasons") or [],
            "trade_entry_ok": trade_entry.get("ok"),
            "trade_entry_reason": self._normalize_reason_list(trade_entry.get("reason")),
        }
        if log and log[-1].get("timestamp") == event["timestamp"] and log[-1].get("strategy_id") == event["strategy_id"]:
            log[-1] = event
        else:
            log.append(event)
        state["signal_log"] = log[-200:]

    def run_eod_review(self, *, force: bool = False) -> dict[str, Any]:
        """Run end-of-day self-review on today's trade log."""
        state = self.get_state()
        config = self.get_config()
        today = trading_day_key()
        if not force and state.get("last_eod_review_day") == today and state.get("eod_review"):
            return state["eod_review"]

        market_regime = state.get("last_market_regime") or {}
        mtf = state.get("last_mtf_context") or {}
        macro = config.get("macro_inputs") or state.get("macro_inputs") or {}

        review = run_eod_self_review(
            instrument_key=self.instrument_key,
            trades=state.get("trade_history") or [],
            regime=str(market_regime.get("regime") or market_regime.get("scalp_regime") or "RANGING"),
            vix=float(macro.get("vix") or 15),
            trend_direction=str(mtf.get("trend_1h") or "neutral"),
            day=today,
        )
        summary = build_session_summary(
            day=today,
            trades=state.get("trade_history") or [],
            signal_log=state.get("signal_log"),
            regime=str(market_regime.get("regime") or market_regime.get("scalp_regime") or "RANGING"),
            daily_pnl=float(state.get("daily_pnl") or 0),
        )
        summaries = [s for s in (state.get("session_summaries") or []) if s.get("day") != today]
        state["session_summaries"] = (summaries + [summary])[-30:]
        state["eod_review"] = review
        state["last_eod_review_day"] = today
        save_eod_review(self.redis, self.user_id, self.instrument_key, review)
        self._save_state(state)
        return review

    def run_weekly_tune(self, *, apply: bool = False, days: int = 5) -> dict[str, Any]:
        """Analyse last N sessions and optionally apply parameter patch to desk config."""
        state = self.get_state()
        config = self.get_config()
        tuning = tune_weekly_parameters(
            config=config,
            trades=state.get("trade_history") or [],
            session_summaries=state.get("session_summaries"),
            signal_log=state.get("signal_log"),
            days=days,
        )
        if apply and tuning.get("mode") != "hold":
            params = dict(config.get("params") or {})
            for key, value in config_patch_from_tuning(tuning).items():
                if value is not None:
                    params[key] = value
            config["params"] = params
            config["last_weekly_tune_at"] = tuning.get("generated_at")
            self.save_config(config)
            tuning["applied"] = True
            tuning["applied_params"] = params
        else:
            tuning["applied"] = False
        state["weekly_tuning"] = tuning
        save_weekly_tuning(self.redis, self.user_id, self.instrument_key, tuning)
        self._save_state(state)
        return tuning

    def get_pattern_memory(self, *, limit: int = 20) -> dict[str, Any]:
        patterns = load_pattern_memory(self.redis, self.user_id, self.instrument_key)
        return {
            "patterns": patterns[-limit:],
            "count": len(patterns),
            "last_pattern": (self.get_state().get("last_pattern")),
        }

    def get_loss_autopsies(self, *, limit: int = 20) -> dict[str, Any]:
        autopsies = load_loss_autopsies(self.redis, self.user_id, self.instrument_key)
        return {
            "autopsies": autopsies[-limit:],
            "count": len(autopsies),
            "last_loss_autopsy": self.get_state().get("last_loss_autopsy"),
        }

    def get_win_reinforcements(self, *, limit: int = 20) -> dict[str, Any]:
        reinforcements = load_win_reinforcements(self.redis, self.user_id, self.instrument_key)
        return {
            "reinforcements": reinforcements[-limit:],
            "count": len(reinforcements),
            "last_win_reinforcement": self.get_state().get("last_win_reinforcement"),
        }

    def _maybe_auto_eod_review(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any] | None:
        """Auto-run once after 15:15 IST when trades exist."""
        today = trading_day_key()
        if state.get("last_eod_review_day") == today and state.get("eod_review"):
            return state.get("eod_review")
        now = to_ist(None)
        after_close = now.hour > 15 or (now.hour == 15 and now.minute >= 15)
        if not after_close:
            return state.get("eod_review")
        if not state.get("trade_history") and int(state.get("trades_today") or 0) == 0:
            return state.get("eod_review")
        return self.run_eod_review(force=True)

    def _smc_dashboard(
        self,
        state: dict,
        selection: dict | None,
        config: dict,
    ) -> dict[str, Any]:
        """Live SMC tracking stats for dashboard."""
        active = (state.get("active_trades") or [None])[0] if state.get("active_trades") else None
        trades = int(state.get("trades_today") or 0)
        wins = int(state.get("wins_today") or 0)
        ctx = (selection or {}).get("market_context") or {}
        bias = ctx.get("bias_15m") or ctx.get("direction") or (selection or {}).get("regime", "neutral")
        if isinstance(bias, str) and bias.isupper():
            bias = bias.lower()
        return {
            "win_rate": round(wins / trades * 100, 1) if trades else 0,
            "pnl": round(float(state.get("daily_pnl") or 0), 2),
            "active_trade": active,
            "strategy_name": (selection or {}).get("selected_label") or config.get("strategy_label"),
            "strategy_id": (selection or {}).get("selected_strategy") or config.get("fixed_strategy_id"),
            "market_bias": bias,
            "strategy_family": config.get("strategy_family", "adaptive"),
            "paper_mode": False,
        }

    async def _load_smc_backtest_candles(
        self,
        from_date: str,
        to_date: str,
    ) -> tuple[pd.DataFrame, str, list[str]]:
        """Load SMC backtest candles with Angel One → DB → demo fallbacks."""
        notes: list[str] = []
        inst = self.scrip.index_token(self.meta["underlying"])
        if not inst:
            loader = BacktestDataLoader(self.db)
            demo = loader._generate_demo(self.meta["underlying"], "1m", from_date[:10], to_date[:10])
            return demo, "demo", ["Index token unavailable — using synthetic demo data"]

        loader = BacktestDataLoader(self.db)

        try:
            df = await self._fetch_angel_candles_range(inst.token, "1m", from_date, to_date)
            if not df.empty:
                loader.save_candles(inst.token, self.meta["underlying"], "NSE", "1m", df)
            if len(df) >= 100:
                return df, "angel_one", notes
            if not df.empty:
                notes.append(f"Angel One returned only {len(df)} bars — trying other sources")
        except (AngelOneAuthError, AngelOneAPIError, json.JSONDecodeError, ValueError) as exc:
            notes.append(f"Angel One fetch failed: {exc}")
            logger.warning("SMC backtest Angel fetch failed for %s: %s", self.instrument_key, exc)
        except Exception as exc:
            notes.append(f"Angel One fetch error: {exc}")
            logger.exception("SMC backtest unexpected Angel fetch error for %s", self.instrument_key)

        try:
            df, source = await loader.load_candles_async(
                self.user_id,
                self.meta["underlying"],
                inst.token,
                "NSE",
                "1m",
                from_date[:10],
                to_date[:10],
            )
            if len(df) >= 30:
                if source == "demo":
                    notes.append("Using synthetic demo data — connect Angel One for live historical candles")
                return df, source, notes
        except Exception as exc:
            notes.append(f"Fallback load failed: {exc}")
            logger.exception("SMC backtest fallback load failed for %s", self.instrument_key)

        demo = loader._generate_demo(self.meta["underlying"], "1m", from_date[:10], to_date[:10])
        notes.append("Using synthetic demo data")
        return demo, "demo", notes

    async def _prepare_smc_backtest_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Load candles/config (needs DB) before CPU-heavy pipeline."""
        from_date = payload.get("from_date")
        to_date = payload.get("to_date")
        if not from_date or not to_date:
            end = to_ist(None).date()
            start = end - timedelta(days=45)
            from_date = start.isoformat()
            to_date = end.isoformat()

        config = self.get_config()
        df, data_source, load_notes = await self._load_smc_backtest_candles(from_date, to_date)
        smc_params = {**config.get("smc_params", {}), **(payload.get("smc_params") or {})}
        return {
            "df": df,
            "config": config,
            "execution_policy": SCALP_EXECUTION_POLICY,
            "option_execution_policy": config.get("option_execution_policy", "buy_only"),
            "data_source": data_source,
            "load_notes": load_notes,
            "smc_params": smc_params,
            "from_date": from_date,
            "to_date": to_date,
            "optimize": bool(payload.get("optimize", False)),
        }

    def _execute_smc_backtest_prepared(self, ctx: dict[str, Any]) -> dict[str, Any]:
        """CPU-only SMC pipeline — must run with DB session closed."""
        return _execute_smc_backtest_ctx(self.instrument_key, ctx)

    async def run_smc_backtest(self, payload: dict[str, Any]) -> dict[str, Any]:
        """30-day SMC strategy comparison + parameter optimization."""
        ctx = await self._prepare_smc_backtest_run(payload)
        return self._execute_smc_backtest_prepared(ctx)

    async def _load_desk_backtest_candles(
        self,
        from_date: str,
        to_date: str,
        timeframe: str = "1m",
    ) -> tuple[pd.DataFrame, str, list[str]]:
        """Load desk backtest candles from Angel One (chunked) with DB cache fallback — no demo."""
        notes: list[str] = []
        inst = self.scrip.index_token(self.meta["underlying"])
        if not inst:
            raise AngelOneAuthError(
                f"{self.meta['underlying']} index token unavailable. Connect Angel One broker and retry."
            )

        loader = BacktestDataLoader(self.db)
        db_df = loader._load_from_db(inst.token, timeframe, from_date[:10], to_date[:10])
        expected_bars = _expected_backtest_bars(from_date, to_date, timeframe)

        try:
            df = await self._fetch_angel_candles_range(inst.token, timeframe, from_date, to_date)
            if not df.empty:
                saved = loader.save_candles(
                    inst.token, self.meta["underlying"], "NSE", timeframe, df
                )
                if saved:
                    notes.append(f"Cached {saved:,} Angel One bars to database")
            merged = _merge_ohlcv(db_df, df)
            if len(df) >= expected_bars * BACKTEST_MIN_COVERAGE_RATIO:
                return df, "angel_one", notes
            if len(merged) >= expected_bars * BACKTEST_MIN_COVERAGE_RATIO:
                notes.append(
                    f"Angel One returned {len(df):,} bars; merged with database cache to {len(merged):,}"
                )
                return merged, "angel_one", notes
            if len(df) >= BACKTEST_MIN_BARS:
                notes.append(f"Angel One returned only {len(df)} bars for the requested range")
                return (merged if len(merged) > len(df) else df), "angel_one", notes
            if not df.empty:
                notes.append(f"Angel One returned only {len(df)} bars for the requested range")
        except AngelOneAuthError:
            raise
        except (AngelOneAPIError, json.JSONDecodeError, ValueError) as exc:
            notes.append(f"Angel One fetch failed: {exc}")
            logger.warning("Desk backtest Angel fetch failed for %s: %s", self.instrument_key, exc)
        except Exception as exc:
            notes.append(f"Angel One fetch error: {exc}")
            logger.exception("Desk backtest unexpected Angel fetch error for %s", self.instrument_key)

        if len(db_df) >= BACKTEST_MIN_BARS:
            notes.append("Using cached database candles (Angel One live fetch unavailable)")
            if len(db_df) < expected_bars * BACKTEST_MIN_COVERAGE_RATIO:
                notes.append(
                    f"Sparse cache: {len(db_df):,} bars for ~{expected_bars:,} expected — reconnect Angel One and retry"
                )
            return db_df, "database", notes

        detail = (
            f"Angel One historical data unavailable for the last {BACKTEST_MAX_DAYS} days. "
            "Connect broker, verify session, and retry."
        )
        if notes:
            detail = f"{detail} ({'; '.join(notes)})"
        raise AngelOneAuthError(detail)

    async def _prepare_desk_backtest_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        timeframe = payload.get("timeframe") or "1m"
        from_date = payload.get("from_date")
        to_date = payload.get("to_date")

        end = to_ist(None).date()
        if not from_date or not to_date:
            start = end - timedelta(days=BACKTEST_MAX_DAYS)
            from_date = start.isoformat()
            to_date = end.isoformat()
        else:
            start = datetime.strptime(from_date[:10], "%Y-%m-%d").date()
            end = datetime.strptime(to_date[:10], "%Y-%m-%d").date()

        requested_start = start
        range_capped = (end - start).days > BACKTEST_MAX_DAYS
        if range_capped:
            start = end - timedelta(days=BACKTEST_MAX_DAYS)
            from_date = start.isoformat()

        config = self.get_config()
        if payload.get("capital") is not None:
            config = {**config, "capital": float(payload["capital"])}
        if payload.get("max_loss_per_day") is not None:
            config = {**config, "max_loss_per_day": float(payload["max_loss_per_day"])}
        if payload.get("capital_utilization_pct") is not None:
            config = {**config, "capital_utilization_pct": float(payload["capital_utilization_pct"])}

        df, data_source, load_notes = await self._load_desk_backtest_candles(from_date, to_date, timeframe)
        expected_bars = _expected_backtest_bars(from_date, to_date, timeframe)
        coverage_pct = round(len(df) / max(expected_bars, 1) * 100, 1) if expected_bars else None
        data_insufficient = bool(expected_bars and len(df) < expected_bars * BACKTEST_MIN_COVERAGE_RATIO)

        range_note = None
        if range_capped:
            range_note = (
                f"Date range capped to {BACKTEST_MAX_DAYS} days "
                f"(requested {(end - requested_start).days + 1} days)"
            )

        return {
            "df": df,
            "config": config,
            "execution_policy": SCALP_EXECUTION_POLICY,
            "option_execution_policy": config.get("option_execution_policy", "buy_only"),
            "timeframe": timeframe,
            "range_capped": range_capped,
            "range_note": range_note,
            "strategy_code": payload.get("strategy_code"),
            "evaluation_days": payload.get("evaluation_days"),
            "ai_entry": bool(payload.get("ai_entry")),
            "ai_exit": bool(payload.get("ai_exit")),
            "data_source": data_source,
            "load_notes": load_notes,
            "from_date": from_date,
            "to_date": to_date,
            "expected_bars": expected_bars,
            "coverage_pct": coverage_pct,
            "data_insufficient": data_insufficient,
        }

    async def run_backtest(self, payload: dict[str, Any]) -> dict[str, Any]:
        ctx = await self._prepare_desk_backtest_run(payload)
        return _execute_desk_backtest_ctx(self.instrument_key, ctx)

    def start_desk_backtest_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        return queue_desk_backtest_job(self.user_id, self.instrument_key, payload)

    def start_smc_backtest_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        return queue_smc_backtest_job(self.user_id, self.instrument_key, payload)

    def apply_smc_recommendation(self, report: dict[str, Any]) -> dict[str, Any]:
        """Wire winning SMC strategy into live desk config."""
        config = self.get_config()
        rec = report.get("recommendation") or {}
        config["strategy_family"] = "smc"
        config["strategy_mode"] = rec.get("strategy_mode", "manual")
        config["fixed_strategy_id"] = rec.get("fixed_strategy_id") or report.get("best_strategy_id")
        if rec.get("smc_params"):
            config["smc_params"] = rec["smc_params"]
            config.setdefault("params", {}).update(rec["smc_params"])
        config["auto_trading_enabled"] = False
        config["strategy_label"] = report.get("best_strategy_label") or "SMC Scalping"
        self.save_config(config)
        return {"ok": True, "config": config, "paper_mode": False}

    async def _fetch_angel_candles_range(
        self, token: str, timeframe: str, from_date: str, to_date: str
    ) -> pd.DataFrame:
        start = datetime.strptime(from_date[:10], "%Y-%m-%d").date()
        end = datetime.strptime(to_date[:10], "%Y-%m-%d").date()
        frames: list[pd.DataFrame] = []
        cur = start
        skipped = 0
        while cur <= end:
            chunk_end = min(cur + timedelta(days=BACKTEST_CHUNK_DAYS - 1), end)
            chunk_df = await self._fetch_angel_candles_chunk_with_retry(
                token, timeframe, cur.isoformat(), chunk_end.isoformat()
            )
            if chunk_df.empty:
                skipped += 1
            else:
                frames.append(chunk_df)
            cur = chunk_end + timedelta(days=1)
            if cur <= end:
                await asyncio.sleep(BACKTEST_CHUNK_DELAY_SEC)
        if not frames:
            return pd.DataFrame()
        if skipped:
            logger.warning(
                "Angel candle range %s..%s kept %s chunks and skipped %s (rate limit or invalid window)",
                from_date,
                to_date,
                len(frames),
                skipped,
            )
        merged = pd.concat(frames, ignore_index=True)
        merged["timestamp"] = pd.to_datetime(merged["timestamp"], errors="coerce")
        return merged.dropna(subset=["timestamp"]).drop_duplicates(subset=["timestamp"]).sort_values(
            "timestamp"
        ).reset_index(drop=True)

    async def _fetch_angel_candles_chunk_with_retry(
        self, token: str, timeframe: str, from_date: str, to_date: str
    ) -> pd.DataFrame:
        last_exc: Exception | None = None
        for attempt in range(BACKTEST_CHUNK_RETRIES):
            try:
                return await self._fetch_angel_candles_once(token, timeframe, from_date, to_date)
            except AngelOneAPIError as exc:
                last_exc = exc
                kind = classify_angel_chunk_error(str(exc))
                if kind == "skip":
                    logger.warning(
                        "Skipping Angel candle chunk %s..%s: %s",
                        from_date,
                        to_date,
                        exc,
                    )
                    return pd.DataFrame()
                if kind == "rate_limit" and attempt < BACKTEST_CHUNK_RETRIES - 1:
                    wait = angel_rate_limit_wait_sec(attempt, BACKTEST_RATE_LIMIT_WAIT_SEC)
                    logger.warning(
                        "Angel rate limit on candle chunk %s..%s (attempt %s/%s); waiting %.0fs",
                        from_date,
                        to_date,
                        attempt + 1,
                        BACKTEST_CHUNK_RETRIES,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                if kind == "rate_limit":
                    logger.warning(
                        "Angel rate limit persisted for chunk %s..%s; keeping other chunks",
                        from_date,
                        to_date,
                    )
                    return pd.DataFrame()
                if exc.status_code == 403 and attempt < BACKTEST_CHUNK_RETRIES - 1:
                    await asyncio.sleep(0.9 * (attempt + 1))
                    continue
                raise
            except Exception as exc:
                last_exc = exc
                if classify_angel_chunk_error(str(exc)) == "rate_limit":
                    if attempt < BACKTEST_CHUNK_RETRIES - 1:
                        wait = angel_rate_limit_wait_sec(attempt, BACKTEST_RATE_LIMIT_WAIT_SEC)
                        logger.warning(
                            "Angel rate limit on candle chunk %s..%s (attempt %s/%s); waiting %.0fs",
                            from_date,
                            to_date,
                            attempt + 1,
                            BACKTEST_CHUNK_RETRIES,
                            wait,
                        )
                        await asyncio.sleep(wait)
                        continue
                    logger.warning(
                        "Angel rate limit persisted for chunk %s..%s; keeping other chunks",
                        from_date,
                        to_date,
                    )
                    return pd.DataFrame()
                if attempt < BACKTEST_CHUNK_RETRIES - 1:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise
        if last_exc:
            raise last_exc
        return pd.DataFrame()

    async def _fetch_angel_candles_once(
        self, token: str, timeframe: str, from_date: str, to_date: str
    ) -> pd.DataFrame:
        db = SessionLocal()
        try:
            manager = AngelOneSessionManager(db, self.redis)
            interval = LOADER_INTERVAL_MAP.get(timeframe, "ONE_MINUTE")
            window = angel_candle_window(from_date, to_date)
            if window is None:
                return pd.DataFrame()
            from_str, to_str = window
            request = CandleRequest(
                exchange="NSE",
                symboltoken=token,
                interval=interval,
                fromdate=from_str,
                todate=to_str,
            )
            client = await manager.get_client_for_user(self.user_id)
            try:
                response = await client.get_candles(request)
            except AngelOneAuthError:
                logger.warning(
                    "Desk backtest candle fetch auth failed for user=%s instrument=%s; forcing broker reconnect",
                    self.user_id,
                    self.instrument_key,
                )
                await manager.connect_user(self.user_id, force=True)
                client = await manager.get_client_for_user(self.user_id)
                response = await client.get_candles(request)
        finally:
            db.close()
        candles = response.get("data") or []
        records = []
        for row in candles:
            if isinstance(row, (list, tuple)) and len(row) >= 6:
                records.append(
                    {
                        "timestamp": row[0],
                        "open": float(row[1]),
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                        "volume": float(row[5]),
                    }
                )
        return pd.DataFrame(records)

    def optimize_from_backtest(self, backtest_summary: dict[str, Any]) -> dict[str, Any]:
        config = self.get_config()
        result = optimize_strategy_prompt(self.instrument_key, backtest_summary, config.get("params", {}))
        version = save_optimization_history(self.redis, self.instrument_key, result)
        config["strategy_version"] = version
        config["params"] = result["optimized_params"]
        self.save_config(config)
        result["strategy_version"] = version
        return result

    def toggle_auto_trading(self, enabled: bool) -> dict[str, Any]:
        config = self.get_config()
        config["auto_trading_enabled"] = enabled
        self.save_config(config)
        stream_hint: dict[str, Any] = {}
        if enabled:
            stream_hint = _ensure_market_stream_for_scalping(self.redis)
        return {
            "auto_trading_enabled": enabled,
            **stream_hint,
        }

    async def _resolve_option_exit_price(self, trade: dict[str, Any]) -> float | None:
        token = trade.get("option_token")
        if token:
            tick = self.bus.get_tick(2, str(token))
            if tick and tick.get("ltp"):
                return float(tick["ltp"])
        entry = trade.get("entry")
        return float(entry) if entry else None

    async def _place_scalping_option_buy(
        self,
        signal: dict[str, Any],
        trade: dict[str, Any],
        *,
        execution_mode: str,
    ) -> dict[str, Any]:
        """BUY CE (CALL) or BUY PE (PUT) — long options only."""
        symbol = str(signal.get("option_symbol") or "")
        if not validate_option_buy_contract(symbol, str(signal.get("signal_type") or "")):
            return {
                "ok": False,
                "reason": [f"Buy-only desk: need CE/PE contract, got {symbol or 'missing'}"],
            }

        lots = int(trade.get("lots") or 1)
        lot_size = self._resolve_option_lot_size(str(signal.get("option_token") or ""))
        remaining = lots * lot_size
        freeze_cap = snap_qty_to_lot(NFO_MAX_ORDER_QTY, lot_size) or remaining
        if remaining < lot_size:
            return {"ok": False, "reason": ["Quantity is not a valid lot multiple"]}
        chunk_count = max(1, (remaining + freeze_cap - 1) // freeze_cap)
        try:
            self.redis.expire(entry_lock_key(self.user_id, self.instrument_key), max(90, 25 * chunk_count))
        except Exception:
            pass

        premium = max(float(signal.get("entry") or 0), 0.0)
        starting_cash = await self._fetch_broker_available_cash()
        executor = OrderExecutor(self.db, self.user_id)
        filled_qty = 0
        order_ids: list[str] = []
        last_entry = premium
        last_db_id = None
        errors: list[str] = []

        while remaining >= lot_size:
            chunk = min(remaining, freeze_cap)
            if filled_qty > 0:
                await asyncio.sleep(0.8)
                cash = await self._fetch_broker_available_cash()
                prem = max(premium, last_entry)
                local_left = None
                if starting_cash is not None and prem > 0:
                    local_left = float(starting_cash) - filled_qty * prem
                budget = local_left
                if cash is not None:
                    budget = min(float(cash), local_left) if local_left is not None else float(cash)
                affordable = lots_affordable_from_cash(budget or 0, prem, lot_size) * lot_size
                chunk = min(chunk, affordable)
                if chunk < lot_size:
                    logger.warning(
                        "Scalping split entry stopped — remaining cash cannot fund another lot instrument=%s filled=%s",
                        self.instrument_key,
                        filled_qty,
                    )
                    break

            placed = await self._place_buy_chunk(
                executor,
                signal,
                symbol,
                chunk,
                lot_size,
            )
            if not placed.get("ok"):
                msg = str((placed.get("reason") or ["order failed"])[0])
                if filled_qty > 0 and "insufficient" in msg.lower():
                    avail, require = parse_insufficient_funds_amounts(msg)
                    if avail and require and require > 0:
                        unit_cost = require / chunk
                        retry_budget = avail
                        if starting_cash is not None and last_entry > 0:
                            local_left = float(starting_cash) - filled_qty * last_entry
                            retry_budget = min(avail, local_left)
                        retry_qty = snap_qty_to_lot(int((retry_budget * 0.97) / unit_cost), lot_size)
                        retry_qty = min(retry_qty, remaining, freeze_cap)
                        if retry_qty >= lot_size and retry_qty < chunk:
                            logger.warning(
                                "Scalping retrying smaller entry chunk instrument=%s qty=%s -> %s",
                                self.instrument_key,
                                chunk,
                                retry_qty,
                            )
                            placed = await self._place_buy_chunk(
                                executor,
                                signal,
                                symbol,
                                retry_qty,
                                lot_size,
                            )
                            chunk = retry_qty
                if not placed.get("ok"):
                    errors.append(msg)
                    break

            filled = int(placed.get("qty") or chunk)
            filled_qty += filled
            remaining -= filled
            oid = str(placed.get("order_id") or "")
            if oid:
                order_ids.append(oid)
            last_db_id = placed.get("db_id")
            last_entry = float(placed.get("entry") or last_entry)
            logger.info(
                "Scalping live entry chunk instrument=%s symbol=%s qty=%s order=%s",
                self.instrument_key,
                symbol,
                filled,
                oid,
            )

        if filled_qty <= 0:
            return {"ok": False, "reason": errors or ["Live entry failed"]}
        filled_lots = max(1, filled_qty // max(lot_size, 1))
        trade["lots"] = filled_lots
        if errors:
            logger.warning(
                "Scalping live entry partial fill instrument=%s symbol=%s lots=%s/%s errors=%s",
                self.instrument_key,
                symbol,
                filled_lots,
                lots,
                errors,
            )
        return {
            "ok": True,
            "order_id": order_ids[0] if order_ids else None,
            "order_ids": order_ids,
            "db_id": last_db_id,
            "entry": last_entry,
            "lots": filled_lots,
            "qty": filled_qty,
        }

    async def _place_buy_chunk(
        self,
        executor: OrderExecutor,
        signal: dict[str, Any],
        symbol: str,
        qty: int,
        lot_size: int,
    ) -> dict[str, Any]:
        payload = OrderCreateRequest(
            symbol=symbol,
            symboltoken=str(signal.get("option_token") or ""),
            exchange=self.meta.get("option_exchange") or "NFO",
            side="BUY",
            qty=qty,
            order_type="MARKET",
            price=float(signal.get("entry") or 0),
            stoploss=float(signal.get("stoploss") or 0),
            product="INTRADAY",
        )
        try:
            order = await executor.place_order(
                payload,
                desk=f"scalping:{self.instrument_key}",
                lot_size=lot_size,
                strategy_code=str(signal.get("strategy_code") or ""),
            )
        except OrderRejectedError as exc:
            return {"ok": False, "reason": [str(exc)]}
        except AngelOneAPIError as exc:
            logger.warning(
                "Scalping broker entry rejected instrument=%s symbol=%s qty=%s error=%s",
                self.instrument_key,
                symbol,
                qty,
                exc,
            )
            return {"ok": False, "reason": [str(exc)]}
        return {
            "ok": True,
            "order_id": order.get("broker_order_id") or order.get("order_id") or order.get("id"),
            "db_id": order.get("id"),
            "entry": order.get("entry") or order.get("price") or payload.price,
            "qty": int(order.get("qty") or qty),
        }

    async def _close_scalping_option_position(
        self,
        trade: dict[str, Any],
        *,
        exit_premium: float | None,
        reason: str,
    ) -> bool:
        if trade.get("execution_mode") != "live":
            trade["execution_mode"] = "live"

        symbol = str(trade.get("option_symbol") or "")
        lot_size = self._resolve_option_lot_size(str(trade.get("option_token") or ""))
        qty = await self._live_close_qty(trade, lot_size)
        if qty <= 0:
            logger.warning("Scalping live close skipped — no net qty for %s", symbol)
            return True

        executor = OrderExecutor(self.db, self.user_id)
        try:
            for chunk in chunk_order_qty(qty, lot_size):
                payload = OrderCreateRequest(
                    symbol=symbol,
                    symboltoken=str(trade.get("option_token") or ""),
                    exchange=self.meta.get("option_exchange") or "NFO",
                    side="SELL",
                    qty=chunk,
                    order_type="MARKET",
                    price=float(exit_premium or trade.get("entry") or 0),
                    product="INTRADAY",
                )
                await executor.place_order(
                    payload,
                    desk=f"scalping:{self.instrument_key}",
                    lot_size=lot_size,
                    is_closing_order=True,
                )
                logger.info(
                    "Scalping live close sent instrument=%s symbol=%s qty=%s reason=%s",
                    self.instrument_key,
                    symbol,
                    chunk,
                    reason,
                )
        except (OrderRejectedError, AngelOneAPIError) as exc:
            logger.warning("Scalping live close rejected symbol=%s error=%s", symbol, exc)
            return False
        return True

    async def _place_direct_close_chunk(
        self,
        *,
        symbol: str,
        symboltoken: str,
        qty: int,
        exit_premium: float | None,
    ) -> dict[str, Any]:
        """Emergency exit path that bypasses allocation gates for live closes."""
        client = await AngelOneSessionManager(self.db, self.redis).get_client_for_user(self.user_id)
        request = PlaceOrderRequest(
            variety="NORMAL",
            tradingsymbol=symbol,
            symboltoken=symboltoken,
            transactiontype="SELL",
            exchange=self.meta.get("option_exchange") or "NFO",
            ordertype="MARKET",
            producttype="INTRADAY",
            duration="DAY",
            price=str(float(exit_premium or 0)),
            quantity=str(int(qty)),
        )
        return await client.place_order(request)

    async def emergency_close_active_trade(self) -> dict[str, Any]:
        """Manual kill switch for the first active live trade on this desk."""
        state = self.get_state()
        active = list(state.get("active_trades") or [])
        trade = active[0] if active else None
        if not trade:
            return {"ok": False, "message": "No active trade to close"}

        exit_premium = await self._resolve_option_exit_price(trade)
        closed_ok = await self._close_scalping_option_position(
            trade,
            exit_premium=exit_premium,
            reason="manual emergency close",
        )
        used_direct = False
        if not closed_ok:
            symbol = str(trade.get("option_symbol") or "")
            token = str(trade.get("option_token") or "")
            lot_size = self._resolve_option_lot_size(token)
            qty = await self._live_close_qty(trade, lot_size)
            if qty > 0 and symbol and token:
                try:
                    for chunk in chunk_order_qty(qty, lot_size):
                        await self._place_direct_close_chunk(
                            symbol=symbol,
                            symboltoken=token,
                            qty=chunk,
                            exit_premium=exit_premium,
                        )
                    closed_ok = True
                    used_direct = True
                except AngelOneAPIError as exc:
                    logger.warning("Emergency direct close rejected symbol=%s error=%s", symbol, exc)
                    return {"ok": False, "message": str(exc)}

        if not closed_ok:
            return {"ok": False, "message": "Failed to close active trade"}

        remaining = active[1:]
        history = list(state.get("trade_history") or [])
        history.append(
            {
                **trade,
                "status": "closed",
                "exit_reason": "manual_emergency_close",
                "exit_time": datetime.now(timezone.utc).isoformat(),
                "exit": exit_premium,
            }
        )
        state["active_trades"] = remaining
        state["trade_history"] = history[-50:]
        state["last_trade_at"] = datetime.now(timezone.utc).isoformat()
        self._save_state(state)
        return {
            "ok": True,
            "message": "Active trade closed",
            "used_direct_broker_close": used_direct,
            "symbol": trade.get("option_symbol"),
        }

    async def _live_close_qty(self, trade: dict[str, Any], lot_size: int) -> int:
        symbol = str(trade.get("option_symbol") or "")
        broker_qty, looked_up = await self._broker_net_qty_lookup(symbol)
        if broker_qty > 0:
            return broker_qty
        if looked_up:
            # Broker confirms flat — do not invent exit qty from a ghost Redis trade.
            return 0
        lots = max(1, int(trade.get("lots") or 1))
        return lots * lot_size

    async def _broker_net_qty(self, symbol: str) -> int:
        qty, _looked_up = await self._broker_net_qty_lookup(symbol)
        return qty

    async def _broker_net_qty_lookup(self, symbol: str) -> tuple[int, bool]:
        if not symbol:
            return 0, False
        try:
            client = await AngelOneSessionManager(self.db, self.redis).get_client_for_user(self.user_id)
            book = await client.get_positions()
        except Exception:
            logger.debug("Broker position lookup failed for %s", symbol, exc_info=True)
            return 0, False
        want = symbol.upper()
        for row in book.get("data") or []:
            if str(row.get("tradingsymbol") or "").upper() != want:
                continue
            return max(0, int(float(row.get("netqty") or 0))), True
        return 0, True

    async def _hydrate_live_open_trades(self, state: dict[str, Any]) -> dict[str, Any]:
        """Recover lost Redis opens from Angel, and prune ghost opens with netqty=0."""
        last_at = state.get("_live_hydrate_at")
        if last_at:
            try:
                ts = datetime.fromisoformat(str(last_at))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - ts < timedelta(seconds=20):
                    return state
            except ValueError:
                pass
        state["_live_hydrate_at"] = datetime.now(timezone.utc).isoformat()

        active = list(state.get("active_trades") or [])
        if active:
            pruned: list[dict[str, Any]] = []
            dropped = 0
            for trade in active:
                if str(trade.get("execution_mode") or "") != "live":
                    pruned.append(trade)
                    continue
                symbol = str(trade.get("option_symbol") or "")
                net, looked_up = await self._broker_net_qty_lookup(symbol)
                if not looked_up:
                    pruned.append(trade)
                    continue
                if net <= 0:
                    dropped += 1
                    logger.warning(
                        "Pruned ghost live scalping trade instrument=%s symbol=%s order_id=%s",
                        self.instrument_key,
                        symbol,
                        trade.get("order_id"),
                    )
                    hist = list(state.get("trade_history") or [])
                    hist.append(
                        {
                            **trade,
                            "status": "closed",
                            "exit_reason": "broker_flat_or_rejected",
                            "exit_time": datetime.now(timezone.utc).isoformat(),
                            "realized_pnl": 0,
                        }
                    )
                    state["trade_history"] = hist[-50:]
                    continue
                lot_size = max(1, int(self.meta["lot_size"]))
                trade["lots"] = max(1, net // lot_size)
                pruned.append(trade)
            if dropped:
                state["active_trades"] = pruned
                self._save_state(state)
            return state

        prefix = str(self.meta.get("underlying") or "").upper()
        try:
            client = await AngelOneSessionManager(self.db, self.redis).get_client_for_user(self.user_id)
            book = await client.get_positions()
        except Exception:
            logger.debug("Live position hydrate skipped instrument=%s", self.instrument_key, exc_info=True)
            return state

        recovered: list[dict[str, Any]] = []
        lot_size = max(1, int(self.meta["lot_size"]))
        for row in book.get("data") or []:
            symbol = str(row.get("tradingsymbol") or "").upper()
            if prefix == "BANKNIFTY":
                if not symbol.startswith("BANKNIFTY"):
                    continue
            elif prefix == "NIFTY":
                if not symbol.startswith("NIFTY") or symbol.startswith("BANKNIFTY"):
                    continue
            elif prefix and not symbol.startswith(prefix):
                continue
            net = int(float(row.get("netqty") or 0))
            if net <= 0:
                continue
            entry = float(row.get("buyavgprice") or row.get("avgnetprice") or row.get("netprice") or 0)
            sl_px, tgt_px = normalize_long_premium_levels(entry, entry * 1.08, entry * 0.88)
            signal_type = "PUT" if symbol.endswith("PE") else "CALL"
            recovered.append(
                {
                    "status": "open",
                    "execution_mode": "live",
                    "execution_policy": SCALP_EXECUTION_POLICY,
                    "signal_type": signal_type,
                    "option_symbol": str(row.get("tradingsymbol") or symbol),
                    "option_token": str(row.get("symboltoken") or ""),
                    "entry": entry,
                    "target": tgt_px,
                    "stoploss": sl_px,
                    "lots": max(1, net // lot_size),
                    "order_id": "broker-sync",
                    "entry_time": datetime.now(timezone.utc).isoformat(),
                    "entry_spot": 0,
                    "indicators": {"spot": 0, "strategy_id": "broker_sync"},
                }
            )
        if recovered:
            state["active_trades"] = recovered
            self._save_state(state)
            logger.warning(
                "Hydrated %s live scalping position(s) from broker instrument=%s",
                len(recovered),
                self.instrument_key,
            )
        return state

    async def enter_trade_from_signal(
        self,
        signal: dict[str, Any],
        config: dict[str, Any],
        *,
        execution_mode: str = "live",
        strategy_code: str | None = None,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Place a live Angel One entry when a strategy signal is approved."""
        execution_mode = "live"
        desk_state = state if state is not None else self.get_state()
        lock_key = entry_lock_key(self.user_id, self.instrument_key)
        acquired = try_acquire_lock(self.redis, lock_key, ENTRY_LOCK_TTL_SEC)
        if not acquired:
            return {"ok": False, "reason": ["Entry already in progress — duplicate blocked"]}

        try:
            if desk_state.get("active_trades"):
                return {"ok": False, "reason": ["Open trade active — next entry only after exit"]}
            if entry_cooldown_active(self.redis, self.user_id, self.instrument_key):
                return {"ok": False, "reason": ["Entry cooldown after a failed or recent live order"]}

            daily_stop = evaluate_ai_daily_stop(desk_state, config, desk_state.get("last_market_context") or {})
            expiry_handler = desk_state.get("last_expiry_handler")
            guards = guard_status(desk_state, config, daily_stop=daily_stop, expiry_handler=expiry_handler)
            allowed = guards.get("can_enter")
            if not allowed:
                return {"ok": False, "reason": guards["alerts"]}

            symbol = str(signal.get("option_symbol") or "")
            if live_net_qty(self.db, self.user_id, symbol) > 0:
                return {
                    "ok": False,
                    "reason": [f"Live position already open in {symbol} — flatten before a new entry"],
                }
            if live_underlying_net_qty(self.db, self.user_id, str(self.meta.get("underlying") or "")) > 0:
                return {
                    "ok": False,
                    "reason": ["Live Bank/Nifty option position already open — flatten before a new entry"],
                }

            ind = signal.get("indicators") or {}
            prefix = "LIVE"
            sizing = self._resolve_desk_lots(
                config,
                desk_state,
                signal=signal,
                option_ltp=float(signal.get("entry") or ind.get("option_ltp") or 0),
            )
            lots = int(sizing.get("lots") or signal.get("lots") or (signal.get("ai") or {}).get("lots") or 0)
            if sizing.get("action") == "HALT" or lots < 1:
                return {
                    "ok": False,
                    "reason": [sizing.get("reason") or "Unable to size entry from deployable capital"],
                }
            max_lots = int(config.get("max_lots_per_trade") or 0)
            if max_lots > 0:
                lots = min(lots, max_lots)
            if lots < 1:
                return {"ok": False, "reason": ["Lot size after caps is zero"]}
            trade = {
                **signal,
                "status": "open",
                "execution_mode": execution_mode,
                "execution_policy": SCALP_EXECUTION_POLICY,
                "strategy_code": strategy_code,
                "lots": lots,
                "position_sizing": sizing,
                "original_stop_pts": ind.get("index_stop_pts") or signal.get("stop_pts"),
                "entry_time": datetime.now(timezone.utc).isoformat(),
                "entry_spot": ind.get("spot"),
                "stop_pts": ind.get("index_stop_pts"),
                "target_pts": ind.get("index_target_pts"),
                "max_hold_bars": ind.get("max_hold_bars") or max_hold_bars(self.instrument_key),
                "original_target": signal.get("target"),
                "ai_extended": False,
                "order_id": f"{prefix}-{int(datetime.now(timezone.utc).timestamp())}",
            }

            buy = await self._place_scalping_option_buy(signal, trade, execution_mode=execution_mode)
            if not buy.get("ok"):
                if execution_mode == "live":
                    set_entry_cooldown(self.redis, self.user_id, self.instrument_key)
                return buy
            trade["order_id"] = buy.get("order_id") or trade["order_id"]
            if buy.get("order_ids"):
                trade["order_ids"] = buy["order_ids"]
            if buy.get("lots"):
                trade["lots"] = int(buy["lots"])
            if buy.get("entry"):
                trade["entry"] = buy["entry"]

            desk_state["active_trades"] = list(desk_state.get("active_trades") or []) + [trade]
            desk_state["last_trade_at"] = datetime.now(timezone.utc).isoformat()
            self._save_state(desk_state)
            return {"ok": True, "trade": trade, "execution_mode": execution_mode}
        finally:
            release_lock(self.redis, lock_key)


def _desk_backtest_worker(user_id: int, instrument_key: str, job_id: str, payload: dict[str, Any]) -> None:
    """Background adaptive backtest — DB released before CPU replay."""
    redis_client = _redis_client()
    db = SessionLocal()
    ctx: dict[str, Any] | None = None
    try:
        _write_desk_job(
            redis_client,
            user_id,
            job_id,
            {"status": "running", "kind": "adaptive", "progress": 25, "job_id": job_id, "instrument": instrument_key},
        )
        service = ScalpingDeskService(db, user_id, instrument_key)
        ctx = asyncio.run(service._prepare_desk_backtest_run(payload))
    except Exception as exc:
        logger.exception("Desk backtest prepare failed job=%s user=%s", job_id, user_id)
        _write_desk_job(
            redis_client,
            user_id,
            job_id,
            {"status": "failed", "kind": "adaptive", "job_id": job_id, "message": str(exc), "progress": 100},
        )
        return
    finally:
        db.close()

    try:
        _write_desk_job(
            redis_client,
            user_id,
            job_id,
            {"status": "running", "kind": "adaptive", "progress": 55, "job_id": job_id, "instrument": instrument_key},
        )
        result = _execute_desk_backtest_ctx(instrument_key, ctx)
        result["status"] = result.get("status") or "completed"
        result["kind"] = "adaptive"
        result["job_id"] = job_id
        result["progress"] = 100
        _write_desk_job(redis_client, user_id, job_id, result)
        try:
            db = SessionLocal()
            try:
                from trading_shared.backtest.orchestrator import BacktestOrchestrator

                saved = BacktestOrchestrator(db).save_scalping_backtest_result(
                    user_id, instrument_key, payload, result
                )
                if saved:
                    result["run_id"] = saved.id
                    _write_desk_job(redis_client, user_id, job_id, result)
            finally:
                db.close()
        except Exception:
            logger.exception("Could not archive scalping backtest job=%s", job_id)
    except Exception as exc:
        logger.exception("Desk backtest job %s failed user=%s", job_id, user_id)
        _write_desk_job(
            redis_client,
            user_id,
            job_id,
            {"status": "failed", "kind": "adaptive", "job_id": job_id, "message": str(exc), "progress": 100},
        )


def _smc_backtest_worker(user_id: int, instrument_key: str, job_id: str, payload: dict[str, Any]) -> None:
    """Background worker — releases DB before long CPU backtest."""
    redis_client = _redis_client()
    db = SessionLocal()
    ctx: dict[str, Any] | None = None
    try:
        _write_desk_job(
            redis_client,
            user_id,
            job_id,
            {"status": "running", "kind": "smc", "progress": 20, "job_id": job_id, "instrument": instrument_key},
        )
        service = ScalpingDeskService(db, user_id, instrument_key)
        ctx = asyncio.run(service._prepare_smc_backtest_run(payload))
    except Exception as exc:
        logger.exception("SMC backtest prepare failed job=%s user=%s", job_id, user_id)
        _write_desk_job(
            redis_client,
            user_id,
            job_id,
            {"status": "failed", "kind": "smc", "job_id": job_id, "message": str(exc), "progress": 100},
        )
        return
    finally:
        db.close()

    try:
        _write_desk_job(
            redis_client,
            user_id,
            job_id,
            {"status": "running", "kind": "smc", "progress": 45, "job_id": job_id, "instrument": instrument_key},
        )
        result = _execute_smc_backtest_ctx(instrument_key, ctx)
        result["status"] = result.get("status") or "completed"
        result["kind"] = "smc"
        result["job_id"] = job_id
        result["progress"] = 100
        _write_desk_job(redis_client, user_id, job_id, result)
    except Exception as exc:
        logger.exception("SMC backtest job %s failed for user_id=%s", job_id, user_id)
        _write_desk_job(
            redis_client,
            user_id,
            job_id,
            {
                "status": "failed",
                "kind": "smc",
                "job_id": job_id,
                "instrument": instrument_key,
                "message": str(exc),
                "progress": 100,
            },
        )


def _ensure_market_stream_for_scalping(redis_client: redis.Redis) -> dict[str, Any]:
    """Mark Live Market Engine as desired ON — required for scalping auto entries/ticks.

    market-data-service reconnects within ~30s when desired=on. Does not turn stream OFF
    when auto is disabled (user controls that from Overview).
    """
    from trading_shared.market.constants import REDIS_STREAM_DESIRED_KEY

    redis_client.set(REDIS_STREAM_DESIRED_KEY, "on")
    return {
        "market_stream_desired": True,
        "message": "Scalping auto needs Live Market Engine ON — stream marked desired; it will connect shortly if Angel One is linked.",
    }


def iter_auto_enabled_desks(redis_url: str) -> list[tuple[int, str]]:
    """Return (user_id, instrument_key) pairs with auto_trading_enabled in desk config."""
    client = redis.from_url(redis_url, decode_responses=True)
    desks: list[tuple[int, str]] = []
    for key in client.scan_iter(f"{REDIS_DESK_PREFIX}:*:{REDIS_CONFIG_SUFFIX}"):
        parts = key.split(":")
        if len(parts) != 5 or parts[0] != "scalping" or parts[1] != "desk":
            continue
        instrument_key = parts[3]
        if instrument_key not in INSTRUMENTS:
            continue
        try:
            user_id = int(parts[2])
        except ValueError:
            continue
        raw = client.get(key)
        if raw and json.loads(raw).get("auto_trading_enabled"):
            desks.append((user_id, instrument_key))
    return desks


def iter_stream_desks(redis_url: str) -> list[tuple[int, str]]:
    """Desks that need the 1s worker: auto-on, or already holding an open trade."""
    client = redis.from_url(redis_url, decode_responses=True)
    desks: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for pair in iter_auto_enabled_desks(redis_url):
        desks.append(pair)
        seen.add(pair)
    for key in client.scan_iter(f"{REDIS_DESK_PREFIX}:*:{REDIS_STATE_SUFFIX}"):
        parts = key.split(":")
        if len(parts) != 5 or parts[0] != "scalping" or parts[1] != "desk":
            continue
        instrument_key = parts[3]
        if instrument_key not in INSTRUMENTS:
            continue
        try:
            user_id = int(parts[2])
        except ValueError:
            continue
        pair = (user_id, instrument_key)
        if pair in seen:
            continue
        raw = client.get(key)
        if not raw:
            continue
        try:
            state = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if state.get("active_trades"):
            desks.append(pair)
            seen.add(pair)
    return desks


def run_scalping_desk_auto_sync(
    db: Session,
    user_id: int,
    instrument_key: str,
    *,
    stream_cycle: bool = False,
) -> dict[str, Any]:
    """Background auto-trading cycle — same logic as POST /evaluate when auto is ON."""
    service = ScalpingDeskService(db, user_id, instrument_key)
    cfg = service.get_config()
    state = service.get_state()
    if not cfg.get("auto_trading_enabled") and not state.get("active_trades"):
        return {"skipped": ["Auto trading disabled"], "instrument": instrument_key}
    _release_request_db(db)
    payload = asyncio.run(service.evaluate_desk(stream_cycle=stream_cycle))
    signal = payload.get("signal") or {}
    trade_entry = signal.get("trade_entry")
    summary = payload.get("daily_summary") or {}
    return {
        "instrument": instrument_key,
        "signal_status": signal.get("status"),
        "trade_entry": trade_entry,
        "active_trades": len(payload.get("active_trades") or []),
        "daily_pnl": summary.get("daily_pnl"),
        "guards": payload.get("guards"),
        "skipped_alerts": (payload.get("guards") or {}).get("alerts") or [],
        "last_stream_eval_at": payload.get("last_stream_eval_at"),
        "stream_status": payload.get("stream_status"),
        "last_live_entry_attempt": payload.get("last_live_entry_attempt"),
        "last_live_entry_failure": payload.get("last_live_entry_failure"),
    }


def run_desk_evaluate(db: Session, user_id: int, instrument_key: str) -> dict[str, Any]:
    service = ScalpingDeskService(db, user_id, instrument_key)
    _release_request_db(db)
    return asyncio.run(service.evaluate_desk())


def run_desk_eod_review(db: Session, user_id: int, instrument_key: str) -> dict[str, Any]:
    service = ScalpingDeskService(db, user_id, instrument_key)
    _release_request_db(db)
    return service.run_eod_review(force=True)


def run_desk_weekly_tune(
    db: Session,
    user_id: int,
    instrument_key: str,
    *,
    apply: bool = False,
    days: int = 5,
) -> dict[str, Any]:
    service = ScalpingDeskService(db, user_id, instrument_key)
    _release_request_db(db)
    return service.run_weekly_tune(apply=apply, days=days)


def run_desk_pattern_memory(db: Session, user_id: int, instrument_key: str, *, limit: int = 20) -> dict[str, Any]:
    service = ScalpingDeskService(db, user_id, instrument_key)
    _release_request_db(db)
    return service.get_pattern_memory(limit=limit)


def run_desk_loss_autopsies(db: Session, user_id: int, instrument_key: str, *, limit: int = 20) -> dict[str, Any]:
    service = ScalpingDeskService(db, user_id, instrument_key)
    _release_request_db(db)
    return service.get_loss_autopsies(limit=limit)


def run_desk_win_reinforcements(db: Session, user_id: int, instrument_key: str, *, limit: int = 20) -> dict[str, Any]:
    service = ScalpingDeskService(db, user_id, instrument_key)
    _release_request_db(db)
    return service.get_win_reinforcements(limit=limit)


def _normalize_desk_paper_trade(trade: dict[str, Any], instrument_key: str, *, open_trade: bool = False) -> dict[str, Any]:
    pnl = trade.get("pnl")
    if pnl is None and open_trade:
        pnl = trade.get("unrealized_pnl")
    pnl_f = float(pnl) if pnl is not None else None
    status = str(trade.get("status") or ("open" if open_trade else "closed"))
    if pnl_f is not None:
        result = "win" if pnl_f > 0 else "loss" if pnl_f < 0 else "breakeven"
    elif open_trade:
        result = "open"
    else:
        result = status
    meta = INSTRUMENTS.get(instrument_key, {})
    label = meta.get("label") or instrument_key
    return {
        "source": "scalping_desk",
        "instrument": instrument_key,
        "symbol": trade.get("option_symbol") or f"{label} {trade.get('signal_type') or ''}".strip(),
        "direction": trade.get("signal_type"),
        "side": trade.get("signal_type"),
        "entry": trade.get("entry") or trade.get("entry_spot"),
        "exit": trade.get("exit"),
        "qty": int(trade.get("lots") or 1),
        "pnl": round(pnl_f, 2) if pnl_f is not None else None,
        "status": status,
        "result": result,
        "order_id": trade.get("order_id"),
        "exit_reason": trade.get("exit_reason"),
        "timestamp": trade.get("entry_time") or trade.get("timestamp"),
        "entry_datetime": trade.get("entry_time") or trade.get("timestamp"),
        "exit_datetime": trade.get("exit_time"),
        "strategy_id": trade.get("strategy_id") or (trade.get("indicators") or {}).get("strategy_id"),
        "strategy_code": trade.get("strategy_code"),
        "mode": trade.get("execution_mode") or "live",
        "ai": trade.get("ai"),
        "indicators": trade.get("indicators"),
        "score": trade.get("score"),
    }


def list_all_desk_paper_trades(db: Session, user_id: int, *, limit: int = 100) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for instrument_key in INSTRUMENTS:
        service = ScalpingDeskService(db, user_id, instrument_key)
        _release_request_db(db)
        state = service.get_state()
        for trade in state.get("active_trades") or []:
            rows.append(_normalize_desk_paper_trade(trade, instrument_key, open_trade=True))
        for trade in (state.get("trade_history") or [])[-limit:]:
            rows.append(_normalize_desk_paper_trade(trade, instrument_key))
    rows.sort(key=lambda r: str(r.get("timestamp") or ""), reverse=True)
    trimmed = rows[:limit]
    wins = sum(1 for r in trimmed if r.get("result") == "win")
    losses = sum(1 for r in trimmed if r.get("result") == "loss")
    total_pnl = round(sum(float(r.get("pnl") or 0) for r in trimmed if r.get("pnl") is not None), 2)
    return {
        "trades": trimmed,
        "count": len(trimmed),
        "summary": {
            "wins": wins,
            "losses": losses,
            "open": sum(1 for r in trimmed if r.get("result") == "open"),
            "total_pnl": total_pnl,
        },
    }


def run_desk_paper_trades(db: Session, user_id: int, *, limit: int = 100) -> dict[str, Any]:
    return list_all_desk_paper_trades(db, user_id, limit=limit)


def run_desk_snapshot(db: Session, user_id: int, instrument_key: str) -> dict[str, Any]:
    service = ScalpingDeskService(db, user_id, instrument_key)
    _release_request_db(db)
    return asyncio.run(service.get_desk_snapshot())


def run_desk_emergency_close(db: Session, user_id: int, instrument_key: str) -> dict[str, Any]:
    service = ScalpingDeskService(db, user_id, instrument_key)
    _release_request_db(db)
    return asyncio.run(service.emergency_close_active_trade())


def run_desk_backtest(db: Session, user_id: int, instrument_key: str, payload: dict) -> dict[str, Any]:
    service = ScalpingDeskService(db, user_id, instrument_key)
    return asyncio.run(service.run_backtest(payload))


def run_desk_smc_backtest(db: Session, user_id: int, instrument_key: str, payload: dict) -> dict[str, Any]:
    """Sync SMC backtest (legacy) — prefer start_smc_backtest_job for long runs."""
    service = ScalpingDeskService(db, user_id, instrument_key)
    return asyncio.run(service.run_smc_backtest(payload))


def apply_desk_smc_recommendation(db: Session, user_id: int, instrument_key: str, payload: dict) -> dict[str, Any]:
    service = ScalpingDeskService(db, user_id, instrument_key)
    return service.apply_smc_recommendation(payload)
