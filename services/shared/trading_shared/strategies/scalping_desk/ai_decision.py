"""AI decision layer for scalping desk — quick entry, quick exit, tight stop."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from trading_shared.ai.decision_engine import DecisionEngine
from trading_shared.ai.features import FeatureExtractor
from trading_shared.ai.regime import RegimeDetector
from trading_shared.ai.scorer import AIScorer
from trading_shared.config import get_settings

from trading_shared.strategies.scalping_desk.constants import (
    AI_CONFIDENCE_ENTER,
    AI_CONFIDENCE_EXIT,
    INSTRUMENTS,
    STRATEGY_LABEL,
)
from trading_shared.strategies.scalping_desk.engine import (
    compute_scalp_risk,
    max_hold_bars,
    premium_risk_from_index,
)
from trading_shared.strategies.scalping_desk.position_sizer import size_from_signal_context
from trading_shared.strategies.scalping_desk.market_regime_classifier import (
    apply_regime_to_position_size,
    apply_regime_to_targets,
    regime_allows_signal,
)
from trading_shared.strategies.scalping_desk.mtf_context_builder import mtf_blocks_signal
from trading_shared.strategies.scalping_desk.entry_signal_validator import (
    validate_from_signal,
    verdict_allows_entry,
)
from trading_shared.strategies.scalping_desk.orb_breakout_confirmation import orb_confirmation_allows_entry
from trading_shared.strategies.scalping_desk.expiry_day_handler import (
    apply_expiry_to_targets,
    expiry_allows_signal,
)
from trading_shared.strategies.scalping_desk.strategies import STRATEGY_REGISTRY

ORB_STRATEGY_IDS = frozenset({"orb_breakout", "smc_orb_fvg"})

logger = logging.getLogger(__name__)


def compute_ai_targets(
    instrument_key: str,
    signal: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """
    AI sets per-trade target/stop from momentum, volatility, and user's daily risk budget.
    User controls capital, max loss/day, max trades/day — not the target amount.
    """
    ind = signal.get("indicators") or {}
    lot_size = int(context.get("lot_size") or INSTRUMENTS[instrument_key]["lot_size"])
    capital = float(context.get("capital") or 100_000)
    max_loss = float(context.get("max_loss_per_day") or 5000)
    max_trades = int(context.get("max_trades_per_day") or 5)
    daily_pnl = float(context.get("current_pnl") or 0)
    trades_today = int(context.get("trades_today") or 0)

    spot = float(ind.get("spot") or 0)
    atr = float(ind.get("atr") or spot * 0.002)
    vol = float(ind.get("volume_ratio") or 1)
    rsi = float(ind.get("rsi") or 50)

    if ind.get("use_fixed_risk"):
        stop_pts = float(ind.get("index_stop_pts") or 7)
        target_pts = float(ind.get("index_target_pts") or stop_pts * 2)
        target_inr = round(target_pts * lot_size, 2)
        entry = float(signal.get("entry") or max(spot * 0.005, 10))
        prem_sl, prem_tgt = premium_risk_from_index(entry, stop_pts, target_pts)
        return {
            "target_pts": target_pts,
            "stop_pts": stop_pts,
            "target_inr": target_inr,
            "stop_inr": round(stop_pts * lot_size, 2),
            "premium_target": prem_tgt,
            "premium_stop": prem_sl,
            "max_hold_bars": int(ind.get("max_hold_bars") or max_hold_bars(instrument_key)),
            "momentum_score": 1.0,
            "reason": f"Fixed RRR {target_pts}/{stop_pts} pts · ₹{target_inr:.0f} target",
        }

    stop_pts, base_target_pts = compute_scalp_risk(spot, atr, instrument_key)

    momentum = 1.0
    if vol >= 1.4:
        momentum += 0.12
    if vol >= 1.8:
        momentum += 0.08
    if signal.get("signal_type") == "CALL" and 48 <= rsi <= 62:
        momentum += 0.05
    if signal.get("signal_type") == "PUT" and 38 <= rsi <= 52:
        momentum += 0.05
    momentum = min(momentum, 1.35)

    target_pts = round(base_target_pts * momentum, 2)

    remaining_trades = max(1, max_trades - trades_today)
    loss_headroom = max(0.0, max_loss + daily_pnl)
    budget_inr = min(
        target_pts * lot_size,
        (loss_headroom / remaining_trades) * 1.4 if loss_headroom else capital * 0.015,
        capital * 0.02,
    )
    target_inr = round(max(budget_inr, 120.0), 2)
    target_pts = round(target_inr / lot_size, 2)

    entry = float(signal.get("entry") or max(spot * 0.005, 10))
    prem_sl, prem_tgt = premium_risk_from_index(entry, stop_pts, target_pts)

    return {
        "target_pts": target_pts,
        "stop_pts": stop_pts,
        "target_inr": target_inr,
        "stop_inr": round(stop_pts * lot_size, 2),
        "premium_target": prem_tgt,
        "premium_stop": prem_sl,
        "max_hold_bars": int(ind.get("max_hold_bars") or max_hold_bars(instrument_key)),
        "momentum_score": round(momentum, 2),
        "reason": (
            f"AI target ₹{target_inr:.0f} ({target_pts} pts × {lot_size} qty) · "
            f"vol {vol:.1f} · {remaining_trades} trades left today"
        ),
    }


def apply_ai_targets(signal: dict[str, Any], targets: dict[str, Any]) -> dict[str, Any]:
    """Merge AI target/stop onto signal for live display and trade tracking."""
    ind = signal.setdefault("indicators", {})
    ind["index_target_pts"] = targets["target_pts"]
    ind["index_stop_pts"] = targets["stop_pts"]
    ind["max_hold_bars"] = targets.get("max_hold_bars") or ind.get("max_hold_bars")
    signal["target_pts"] = targets["target_pts"]
    signal["stop_pts"] = targets["stop_pts"]
    signal["target_inr"] = targets["target_inr"]
    signal["stop_inr"] = targets["stop_inr"]

    entry = float(signal.get("entry") or 0)
    prem_tgt = float(targets["premium_target"])
    prem_sl = float(targets["premium_stop"])
    if signal.get("signal_type") == "CALL":
        signal["target"] = round(entry + prem_tgt, 2)
        signal["stoploss"] = round(entry - prem_sl, 2)
    else:
        signal["target"] = round(entry - prem_tgt, 2)
        signal["stoploss"] = round(entry + prem_sl, 2)
    return signal


def evaluate_ai_decision(
    instrument_key: str,
    signal: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    """
    AI gate for quick scalp entries.
    Favors fast ENTER on momentum; never extends targets.
    """
    payload = {
        "instrument": instrument_key,
        "timeframe": signal.get("timeframe"),
        "signal_type": signal.get("signal_type"),
        "indicators": signal.get("indicators", {}),
        "recent_candles": context.get("recent_candles", []),
        "market_context": context.get("market_context", {}),
        "capital": context.get("capital"),
        "lot_size": context.get("lot_size"),
        "current_pnl": context.get("current_pnl", 0),
        "trades_today": context.get("trades_today", 0),
        "max_loss_per_day": context.get("max_loss_per_day"),
        "max_trades_per_day": context.get("max_trades_per_day"),
    }

    targets = compute_ai_targets(instrument_key, signal, context)
    selection = context.get("strategy_selection") or {}
    market_ctx = context.get("market_context") or selection.get("market_context") or {}
    strategy_id = signal.get("strategy_id") or signal.get("indicators", {}).get("strategy_id", "")

    regime_result = context.get("market_regime") or selection.get("market_regime")
    mtf_result = context.get("mtf_context") or selection.get("mtf_context") or market_ctx.get("mtf")
    orb_confirmation = context.get("orb_confirmation") or selection.get("orb_confirmation")
    expiry_handler = context.get("expiry_handler") or selection.get("expiry_handler")
    lot_size = int(context.get("lot_size") or INSTRUMENTS[instrument_key]["lot_size"])
    if regime_result:
        targets = apply_regime_to_targets({**targets, "lot_size": lot_size}, regime_result)
    if expiry_handler:
        targets = apply_expiry_to_targets(targets, expiry_handler)

    pseudo_state = {
        "daily_pnl": context.get("current_pnl", 0),
        "trades_today": context.get("trades_today", 0),
        "consecutive_losses": context.get("consecutive_losses", 0),
    }
    pseudo_config = {
        "capital": context.get("capital"),
        "max_loss_per_day": context.get("max_loss_per_day"),
        "max_trades_per_day": context.get("max_trades_per_day"),
        "max_daily_loss_pct": context.get("max_daily_loss_pct"),
        "risk_per_trade_pct": context.get("risk_per_trade_pct"),
        "max_lots_per_trade": context.get("max_lots_per_trade", 2),
    }
    position_size = size_from_signal_context(
        instrument_key,
        signal,
        pseudo_state,
        pseudo_config,
        targets,
    )

    if regime_result:
        position_size = apply_regime_to_position_size(position_size, regime_result)

    volume_min = float(context.get("volume_min_ratio") or 1.2)
    entry_validation = validate_from_signal(
        instrument_key,
        signal,
        targets=targets,
        timestamp=signal.get("timestamp"),
        volume_min=volume_min,
    )

    try:
        data_provider = context.get("data_provider")
        if data_provider:
            engine = DecisionEngine(
                FeatureExtractor(data_provider),
                RegimeDetector(data_provider),
                AIScorer(),
            )
        else:
            raise TypeError("no data provider")
        ind = signal.get("indicators", {})
        vol = float(ind.get("volume_ratio", 1))
        wrapped = {
            "symbol": signal.get("option_symbol"),
            "token": signal.get("option_token"),
            "engine": "scalping",
            "side": "BUY",
            "score": min(vol * 18 + 58, 94),
            "confidence": 0.72,
            "metadata": {
                "underlying": context.get("underlying", "NIFTY"),
                "mode": strategy_id or "adaptive_scalp",
                "regime": market_ctx.get("regime"),
            },
        }
        result = engine.evaluate_signal(wrapped)
        confidence = round(result.score, 1)
        action = "ENTER" if confidence >= AI_CONFIDENCE_ENTER else "SKIP"
        if result.action.value == "exit":
            action = "EXIT"
        if position_size.get("action") == "HALT":
            action = "SKIP"
        if regime_result and not regime_allows_signal(regime_result, signal.get("signal_type")):
            action = "SKIP"
        if mtf_result and mtf_blocks_signal(mtf_result, signal.get("signal_type")):
            action = "SKIP"
        battle_strategy = strategy_id in (
            "battle_ema_cross",
            "battle_vwap_bounce",
            "battle_orb",
        ) or str(context.get("strategy_family") or "").lower() == "battle"
        if not battle_strategy and not verdict_allows_entry(entry_validation):
            action = "SKIP"
        elif battle_strategy and entry_validation and entry_validation.get("verdict") == "SKIP":
            action = "SKIP"
        if strategy_id in ORB_STRATEGY_IDS and not orb_confirmation_allows_entry(
            orb_confirmation, signal.get("signal_type")
        ):
            action = "SKIP"
        trend_dir = (mtf_result or {}).get("trend_1h") or market_ctx.get("direction")
        if not expiry_allows_signal(expiry_handler, signal.get("signal_type"), trend_direction=trend_dir):
            action = "SKIP"
        return {
            "action": action,
            "confidence": confidence,
            "reasoning": _entry_reasoning(
                ind, signal.get("signal_type"), confidence, targets, selection, entry_validation
            ),
            "mode": "adaptive_entry",
            "targets": targets,
            "target_inr": targets["target_inr"],
            "exit_style": "tight_sl_quick_target",
            "regime": market_ctx.get("scalp_regime") or market_ctx.get("regime"),
            "market_regime": regime_result,
            "mtf_context": mtf_result,
            "entry_validation": entry_validation,
            "validation_verdict": entry_validation.get("verdict"),
            "validation_score": entry_validation.get("score"),
            "orb_confirmation": orb_confirmation,
            "expiry_handler": expiry_handler,
            "strategy_id": strategy_id,
            "strategy_label": selection.get("selected_label") or STRATEGY_REGISTRY.get(strategy_id, {}).get("label"),
            "position_size": position_size,
            "lots": position_size.get("lots", 0),
            "payload": payload,
        }
    except Exception as exc:
        logger.debug("AI decision fallback for %s: %s", instrument_key, exc)
        return _rule_based_decision(
            payload,
            signal,
            targets,
            selection,
            market_ctx,
            position_size,
            regime_result,
            mtf_result,
            entry_validation,
            orb_confirmation,
            expiry_handler,
        )


def evaluate_ai_exit(
    trade: dict[str, Any],
    spot: float,
    bars_held: int,
    trailing: dict[str, Any] | None = None,
    *,
    df: pd.DataFrame | None = None,
    vwap: float | None = None,
) -> dict[str, Any]:
    """Recommend quick exit on open trades (trail SL / dynamic reasoning / time stop)."""
    from trading_shared.ai.trade_reasoning import evaluate_dynamic_exit

    if trailing and trailing.get("action") == "EXIT":
        return {
            "action": "EXIT",
            "confidence": 95,
            "reasoning": trailing.get("reason") or "Trailing stop hit",
            "mode": "trail_sl_exit",
            "trailing_sl": trailing,
        }
    if trailing and trailing.get("action") == "TIGHTEN":
        return {
            "action": "HOLD",
            "confidence": 72,
            "reasoning": trailing.get("reason") or "Trailing SL tightened",
            "mode": "trail_sl_tighten",
            "trailing_sl": trailing,
        }

    entry_spot = float(trade.get("entry_spot") or trade.get("indicators", {}).get("spot") or spot)
    target_pts = float(trade.get("target_pts") or trade.get("indicators", {}).get("index_target_pts") or 0)
    stop_pts = float(trade.get("stop_pts") or trade.get("indicators", {}).get("index_stop_pts") or 0)
    max_hold = int(trade.get("max_hold_bars") or trade.get("indicators", {}).get("max_hold_bars") or 10)
    move = spot - entry_spot
    if trade.get("signal_type") == "PUT":
        move = -move

    # Dynamic AI exit only for loss management — winners exit via target/trail/time rules.
    if df is not None and not df.empty and move <= 0:
        is_long = str(trade.get("signal_type", "CALL")).upper() != "PUT"
        stop_level = entry_spot - stop_pts if is_long else entry_spot + stop_pts
        target_level = entry_spot + target_pts if is_long else entry_spot - target_pts
        dynamic = evaluate_dynamic_exit(
            engine="scalping",
            side="CALL" if is_long else "PUT",
            entry=entry_spot,
            stop=stop_level,
            target=target_level if target_pts else None,
            strategy=str(trade.get("strategy_id") or "scalp"),
            current=spot,
            candles=df,
            bars_held=bars_held,
            max_hold_bars=max_hold,
            vwap=vwap,
            atr_at_entry=float(trade.get("indicators", {}).get("atr") or 0) or None,
        )
        if dynamic.get("should_exit"):
            return {
                "action": "EXIT",
                "confidence": dynamic.get("confidence_score", 85),
                "reasoning": dynamic.get("reasoning", "Dynamic exit"),
                "mode": "dynamic_exit",
                "dynamic_exit": dynamic,
                "trailing_sl": trailing,
            }
        if dynamic.get("should_tighten") and trailing:
            return {
                "action": "HOLD",
                "confidence": dynamic.get("confidence_score", 72),
                "reasoning": dynamic.get("reasoning", "Tighten stop"),
                "mode": "dynamic_tighten",
                "dynamic_exit": dynamic,
                "trailing_sl": trailing,
            }

    near_target = target_pts > 0 and move >= target_pts * 0.98
    near_stop = stop_pts > 0 and move <= -stop_pts * 0.98
    time_pressure = bars_held >= max_hold

    if near_target:
        return {
            "action": "EXIT",
            "confidence": 88,
            "reasoning": "Price within 95% of quick target — take profit now",
            "mode": "quick_exit",
        }
    if near_stop:
        return {
            "action": "EXIT",
            "confidence": 92,
            "reasoning": "Approaching tight stop — exit to cap loss",
            "mode": "tight_sl_exit",
        }
    if time_pressure:
        return {
            "action": "EXIT",
            "confidence": AI_CONFIDENCE_EXIT,
            "reasoning": f"Max hold {max_hold} bars — time-based quick exit",
            "mode": "time_exit",
        }
    if move > 0 and bars_held >= 3:
        return {
            "action": "HOLD",
            "confidence": 70,
            "reasoning": "In profit — hold for quick target unless time runs out",
            "mode": "quick_hold",
        }
    return {
        "action": "HOLD",
        "confidence": 60,
        "reasoning": "Monitoring tight SL and quick target",
        "mode": "monitor",
    }


def _entry_reasoning(
    ind: dict[str, Any],
    signal_type: str | None,
    confidence: float,
    targets: dict[str, Any],
    selection: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
) -> str:
    vol = float(ind.get("volume_ratio", 1))
    parts = [f"{STRATEGY_LABEL}: entry {confidence}%"]
    if selection:
        label = selection.get("selected_label") or selection.get("selected_strategy")
        regime = selection.get("regime")
        if label:
            parts.append(f"strategy {label}")
        if regime:
            parts.append(f"regime {regime}")
    parts.append(targets.get("reason", f"AI target ₹{targets.get('target_inr', 0):.0f}"))
    if vol >= 1.3:
        parts.append("volume confirmed")
    if signal_type:
        parts.append(f"{signal_type} alignment")
    if validation:
        parts.append(f"validator {validation.get('verdict')} ({validation.get('score')}/5)")
    return "; ".join(parts)


def _rule_based_decision(
    payload: dict[str, Any],
    signal: dict[str, Any],
    targets: dict[str, Any],
    selection: dict[str, Any] | None = None,
    market_ctx: dict[str, Any] | None = None,
    position_size: dict[str, Any] | None = None,
    regime_result: dict[str, Any] | None = None,
    mtf_result: dict[str, Any] | None = None,
    entry_validation: dict[str, Any] | None = None,
    orb_confirmation: dict[str, Any] | None = None,
    expiry_handler: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ind = signal.get("indicators", {})
    rsi_val = float(ind.get("rsi", 50))
    vol = float(ind.get("volume_ratio", 1))
    st = float(ind.get("supertrend", 0))
    signal_type = signal.get("signal_type")

    strategy_id = signal.get("strategy_id") or ind.get("strategy_id", "")
    regime = (market_ctx or {}).get("regime") or (selection or {}).get("regime")

    score = 62.0
    reasons = ["Adaptive scalp rule stack"]
    if selection and selection.get("selected_score", 0) >= 60:
        score += 8
        reasons.append(f"AI picked {selection.get('selected_label', strategy_id)}")
    if vol >= 1.35:
        score += 14
        reasons.append("Strong volume — high win-rate filter passed")
    elif vol >= 1.3:
        score += 10
        reasons.append("Activity spike confirmed")
    if signal_type == "CALL" and st > 0:
        score += 8
        reasons.append("Supertrend bullish")
    if signal_type == "PUT" and st < 0:
        score += 8
        reasons.append("Supertrend bearish")
    if signal_type == "CALL" and 45 <= rsi_val <= 62:
        score += 8
    if signal_type == "PUT" and 38 <= rsi_val <= 55:
        score += 8
    if regime in ("TRENDING_UP", "TRENDING_DOWN") and strategy_id == "trend_follow":
        score += 6
        reasons.append("Trend strategy in trend regime")
    if regime == "RANGING" and strategy_id == "vwap_bounce":
        score += 6
        reasons.append("VWAP bounce in range")
    if regime == "HIGH_VOLATILITY" and strategy_id == "volume_breakout":
        score += 6
        reasons.append("Breakout in high vol")

    action = "ENTER" if score >= AI_CONFIDENCE_ENTER else "SKIP"
    if position_size and position_size.get("action") == "HALT":
        action = "SKIP"
        reasons.append(position_size.get("reason", "position sizer halt"))
    if regime_result and not regime_allows_signal(regime_result, signal_type):
        action = "SKIP"
        reasons.append(f"regime {regime_result.get('regime')} blocks {signal_type}")
    if mtf_result and mtf_blocks_signal(mtf_result, signal_type):
        action = "SKIP"
        reasons.append("MTF counter-trend bias blocks entry")
    if entry_validation and not verdict_allows_entry(entry_validation):
        action = "SKIP"
        reasons.append(
            f"entry validator {entry_validation.get('verdict')} ({entry_validation.get('score')}/5)"
        )
    if strategy_id in ORB_STRATEGY_IDS and not orb_confirmation_allows_entry(
        orb_confirmation, signal_type
    ):
        action = "SKIP"
        oc = orb_confirmation or {}
        reasons.append(
            f"ORB confirm {oc.get('breakout_direction', 'none')} · fake {oc.get('fake_risk', '?')}"
        )
    trend_dir = (mtf_result or {}).get("trend_1h")
    if expiry_handler and not expiry_allows_signal(
        expiry_handler, signal_type, trend_direction=trend_dir
    ):
        action = "SKIP"
        reasons.append(expiry_handler.get("warning") or "expiry window blocks entry")
    return {
        "action": action,
        "confidence": round(min(score, 99), 1),
        "reasoning": "; ".join(reasons + [targets.get("reason", "")]),
        "mode": "adaptive_entry",
        "targets": targets,
        "target_inr": targets["target_inr"],
        "exit_style": "tight_sl_quick_target",
        "regime": (market_ctx or {}).get("scalp_regime") or regime,
        "market_regime": regime_result,
        "mtf_context": mtf_result,
        "entry_validation": entry_validation,
        "validation_verdict": (entry_validation or {}).get("verdict"),
        "validation_score": (entry_validation or {}).get("score"),
        "orb_confirmation": orb_confirmation,
        "expiry_handler": expiry_handler,
        "strategy_id": strategy_id,
        "strategy_label": (selection or {}).get("selected_label"),
        "position_size": position_size,
        "lots": (position_size or {}).get("lots", 0),
        "payload": payload,
    }


def optimize_strategy_prompt(
    instrument_key: str,
    backtest_summary: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Generate AI optimization suggestions from backtest results."""
    win_rate = backtest_summary.get("win_rate", 0)
    profit_factor = backtest_summary.get("profit_factor", 0)
    avg_loss = backtest_summary.get("avg_loss_loss", 0)
    suggestions = []

    if win_rate < 55:
        suggestions.append("Raise activity spike threshold to 1.4 for cleaner entries")
        suggestions.append("Trade only 9:30–11:15 and 13:45–15:00 IST")
    if avg_loss < -600:
        suggestions.append("Tighten stop to 1.0× ATR and reduce max hold to 8 bars")
    if profit_factor < 1.3:
        suggestions.append("Keep quick target at 0.5× ATR — do not extend targets")
    if not suggestions:
        suggestions.append("v3 quick scalp params are balanced — maintain tight SL discipline")

    optimized = {
        **params,
        "volume_spike_ratio": 1.4 if win_rate < 55 else 1.3,
        "target_atr_mult": 0.5 if profit_factor < 1.3 else params.get("target_atr_mult", 0.55),
        "stop_atr_mult": 1.0 if avg_loss < -600 else params.get("stop_atr_mult", 1.2),
        "max_hold_bars": 8 if avg_loss < -600 else params.get("max_hold_bars", 10),
    }

    return {
        "instrument": instrument_key,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis": (
            f"Backtest {instrument_key} (v3 quick scalp): win rate {win_rate}%, "
            f"avg loss ₹{avg_loss}, profit factor {profit_factor}, "
            f"{backtest_summary.get('total_trades', 0)} trades."
        ),
        "suggestions": suggestions,
        "optimized_params": optimized,
    }


def save_optimization_history(redis_client, instrument_key: str, entry: dict[str, Any]) -> int:
    key = f"scalping:desk:{instrument_key}:optimizations"
    raw = redis_client.get(key)
    history = json.loads(raw) if raw else []
    version = len(history) + 1
    history.append({**entry, "version": version})
    redis_client.setex(key, 86400 * 30, json.dumps(history[-20:]))
    redis_client.set(f"scalping:desk:{instrument_key}:strategy_version", version)
    return version
