"""AI strategy picker — selects best scalping strategy from live market context."""

from __future__ import annotations

from typing import Any

import pandas as pd

from trading_shared.ai.types import MarketRegime
from trading_shared.strategies.scalping_desk.engine import ScalpSignal
from trading_shared.strategies.scalping_desk.market_context import build_market_context
from trading_shared.strategies.scalping_desk.strategies import STRATEGY_REGISTRY, list_strategies
from trading_shared.strategies.scalping_desk.strategy_catalog import (
    STRATEGY_CATALOG,
    catalog_for_api,
    code_for_id,
    enabled_codes,
    merge_strategy_settings,
)

MIN_STRATEGY_SCORE = 52


def _smc_registry():
    from trading_shared.strategies.scalping_desk.smc_scalping_engine import (
        SMC_REGISTRY,
        evaluate_smc_best,
        list_smc_strategies,
    )

    return SMC_REGISTRY, evaluate_smc_best, list_smc_strategies


def score_strategies(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Rank strategies for current regime, volume, and direction."""
    regime = context.get("regime", MarketRegime.RANGING.value)
    vol = float(context.get("volume_ratio") or 1)
    trend = float(context.get("trend_strength") or 0)
    direction = context.get("direction", "neutral")
    pcr = float(context.get("pcr") or 1)
    session_ok = bool(context.get("session_ok", True))

    scores: list[dict[str, Any]] = []
    for sid, meta in STRATEGY_REGISTRY.items():
        score = 40.0
        reasons: list[str] = []

        if regime in meta["best_regimes"]:
            score += 22
            reasons.append(f"{regime} fit")
        elif regime == MarketRegime.RANGING.value and sid == "momentum_burst":
            score -= 8
            reasons.append("ranging — lower momentum edge")

        if sid == "momentum_burst":
            if vol >= 1.35:
                score += 12
                reasons.append("strong volume")
            if trend >= 0.05:
                score += 8
                reasons.append("trend separation")
        elif sid == "vwap_bounce":
            if regime in (MarketRegime.RANGING.value, MarketRegime.LOW_VOLATILITY.value):
                score += 15
                reasons.append("sideways market")
            if vol <= 1.4:
                score += 6
                reasons.append("controlled vol")
        elif sid == "trend_follow":
            if regime in (MarketRegime.TRENDING_UP.value, MarketRegime.TRENDING_DOWN.value):
                score += 18
                reasons.append("trend regime")
            if trend >= 0.08:
                score += 10
                reasons.append("strong EMA stack")
        elif sid == "volume_breakout":
            if regime == MarketRegime.HIGH_VOLATILITY.value:
                score += 20
                reasons.append("high volatility")
            if vol >= 1.5:
                score += 12
                reasons.append("volume surge")

        if direction == "up" and sid in ("trend_follow", "momentum_burst", "volume_breakout"):
            score += 5
            reasons.append("bullish flow")
        if direction == "down" and sid in ("trend_follow", "momentum_burst", "volume_breakout"):
            score += 5
            reasons.append("bearish flow")

        if pcr > 1.15 and sid == "vwap_bounce":
            score += 4
            reasons.append("elevated PCR — bounce setups")
        if pcr < 0.85 and sid == "volume_breakout":
            score += 4
            reasons.append("low PCR — breakout bias")

        if not session_ok:
            score -= 25
            reasons.append("outside session")

        scores.append(
            {
                "strategy_id": sid,
                "label": meta["label"],
                "score": round(min(score, 99), 1),
                "reason": ", ".join(reasons) or meta["description"],
            }
        )

    scores.sort(key=lambda x: x["score"], reverse=True)
    return scores


def select_and_evaluate(
    df: pd.DataFrame,
    timeframe: str,
    option_chain: dict[str, Any],
    lot_size: int,
    instrument_key: str,
    *,
    tick: dict[str, Any] | None = None,
    underlying: str = "NIFTY",
    params: dict[str, Any] | None = None,
    strategy_mode: str = "auto",
    fixed_strategy_id: str | None = None,
    strategy_family: str = "adaptive",
    skip_session: bool = False,
    enriched: bool = False,
) -> tuple[ScalpSignal | None, dict[str, Any]]:
    """
    AI picks the best strategy for live conditions, then evaluates for a signal.
    Returns (signal, selection_metadata).
    """
    if strategy_family == "smc":
        _, evaluate_smc_best, list_smc_strategies = _smc_registry()
        smc_params = {**(params or {}), **((params or {}).get("smc_params") or {})}
        fixed = fixed_strategy_id if strategy_mode == "manual" else None
        signal, meta = evaluate_smc_best(
            df,
            timeframe,
            option_chain,
            lot_size,
            instrument_key=instrument_key,
            params=smc_params,
            fixed_strategy_id=fixed,
        )
        meta["mode"] = strategy_mode
        meta["strategy_family"] = "smc"
        meta["rankings"] = [
            {"strategy_id": s["id"], "label": s["label"], "score": 0, "reason": s["description"]}
            for s in list_smc_strategies()
        ]
        return signal, meta

    if strategy_family == "battle":
        from trading_shared.strategies.scalping_desk.battle_tested_scalp import evaluate_battle_best

        fixed = fixed_strategy_id if strategy_mode == "manual" else None
        signal, meta = evaluate_battle_best(
            df,
            timeframe,
            option_chain,
            lot_size,
            instrument_key,
            params=params,
            fixed_strategy_id=fixed,
            skip_session=skip_session,
            enriched=enriched,
        )
        meta["mode"] = strategy_mode
        return signal, meta

    context = build_market_context(
        df, tick=tick, chain=option_chain, underlying=underlying, pre_enriched=enriched
    )
    rankings = score_strategies(context)

    selection: dict[str, Any] = {
        "mode": strategy_mode,
        "strategy_family": "adaptive",
        "regime": context["regime"],
        "market_context": context,
        "rankings": rankings[:4],
        "selected_strategy": None,
        "selected_score": 0,
        "selection_reason": "",
    }

    if strategy_mode == "manual" and fixed_strategy_id:
        order = [fixed_strategy_id] + [r["strategy_id"] for r in rankings if r["strategy_id"] != fixed_strategy_id]
    else:
        order = [r["strategy_id"] for r in rankings if r["score"] >= MIN_STRATEGY_SCORE]
        if not order:
            order = [rankings[0]["strategy_id"]] if rankings else ["momentum_burst"]

    eval_kwargs = {
        "enriched": enriched,
        "instrument_key": instrument_key,
        "params": params,
        "skip_session": skip_session,
    }

    for sid in order:
        meta = STRATEGY_REGISTRY.get(sid)
        if not meta:
            continue
        ranking = next((r for r in rankings if r["strategy_id"] == sid), {})
        signal = meta["evaluate"](df, timeframe, option_chain, lot_size, **eval_kwargs)
        if signal:
            selection["selected_strategy"] = sid
            selection["selected_label"] = meta["label"]
            selection["selected_score"] = ranking.get("score", 0)
            selection["selection_reason"] = ranking.get("reason", meta["description"])
            return signal, selection

    top = rankings[0] if rankings else {}
    selection["selected_strategy"] = top.get("strategy_id")
    selection["selected_label"] = top.get("label")
    selection["selected_score"] = top.get("score", 0)
    selection["selection_reason"] = top.get("reason", "No setup on any strategy")
    return None, selection


def _evaluate_catalog_strategy(
    code: str,
    df: pd.DataFrame,
    timeframe: str,
    option_chain: dict[str, Any],
    lot_size: int,
    instrument_key: str,
    *,
    tick: dict[str, Any] | None = None,
    underlying: str = "NIFTY",
    params: dict[str, Any] | None = None,
    skip_session: bool = False,
    enriched: bool = False,
) -> tuple[ScalpSignal | None, dict[str, Any]]:
    """Evaluate a single catalog strategy by code."""
    meta = STRATEGY_CATALOG.get(code)
    if not meta or instrument_key not in meta.get("instruments", []):
        return None, {}
    sid = meta["id"]
    family = meta["family"]
    if family == "battle":
        from trading_shared.strategies.scalping_desk.battle_tested_scalp import evaluate_battle_best

        signal, sel = evaluate_battle_best(
            df,
            timeframe,
            option_chain,
            lot_size,
            instrument_key,
            params=params,
            fixed_strategy_id=sid,
            skip_session=skip_session,
            enriched=enriched,
        )
    elif family == "smc":
        _, evaluate_smc_best, _ = _smc_registry()
        smc_params = {**(params or {}), **((params or {}).get("smc_params") or {})}
        signal, sel = evaluate_smc_best(
            df,
            timeframe,
            option_chain,
            lot_size,
            instrument_key=instrument_key,
            params=smc_params,
            fixed_strategy_id=sid,
        )
    else:
        reg = STRATEGY_REGISTRY.get(sid)
        if not reg:
            return None, {}
        eval_kwargs = {
            "enriched": enriched,
            "instrument_key": instrument_key,
            "params": params,
            "skip_session": skip_session,
        }
        signal = reg["evaluate"](df, timeframe, option_chain, lot_size, **eval_kwargs)
        sel = {
            "selected_strategy": sid,
            "selected_label": reg["label"],
            "selection_reason": reg["description"],
            "strategy_family": "adaptive",
        }
    sel["selected_strategy_code"] = code
    sel["selected_strategy"] = sid
    sel["selected_label"] = meta["label"]
    sel["strategy_family"] = family
    return signal, sel


def select_from_catalog(
    df: pd.DataFrame,
    timeframe: str,
    option_chain: dict[str, Any],
    lot_size: int,
    instrument_key: str,
    config: dict[str, Any],
    *,
    tick: dict[str, Any] | None = None,
    underlying: str = "NIFTY",
    params: dict[str, Any] | None = None,
    skip_session: bool = False,
    enriched: bool = False,
) -> tuple[ScalpSignal | None, dict[str, Any]]:
    """
    Evaluate enabled catalog strategies for this instrument.
    Manual mode locks to fixed_strategy_code; auto mode tries enabled strategies in priority order.
    """
    settings = merge_strategy_settings(config, instrument_key)
    active_codes = [c for c, s in settings.items() if s.get("enabled")]
    mode = config.get("strategy_mode", "auto")
    fixed_code = config.get("fixed_strategy_code") or code_for_id(
        config.get("fixed_strategy_id") or "",
        instrument_key,
    )

    context = build_market_context(
        df, tick=tick, chain=option_chain, underlying=underlying, pre_enriched=enriched
    )
    rankings = score_strategies(context)

    if mode == "manual" and fixed_code and fixed_code in STRATEGY_CATALOG:
        try_order = [fixed_code]
    else:
        battle = [c for c in active_codes if STRATEGY_CATALOG[c]["family"] == "battle"]
        smc = [c for c in active_codes if STRATEGY_CATALOG[c]["family"] == "smc"]
        adaptive = [c for c in active_codes if STRATEGY_CATALOG[c]["family"] == "adaptive"]
        score_map = {r["strategy_id"]: r["score"] for r in rankings}
        adaptive.sort(
            key=lambda c: score_map.get(STRATEGY_CATALOG[c]["id"], 0),
            reverse=True,
        )
        try_order = battle + adaptive + smc
        if not try_order:
            try_order = [meta["code"] for meta in catalog_for_api(instrument_key, config) if meta.get("enabled")]

    selection: dict[str, Any] = {
        "mode": mode,
        "regime": context.get("regime"),
        "market_context": context,
        "rankings": rankings[:6],
        "enabled_codes": active_codes,
        "try_order": try_order,
        "selected_strategy": None,
        "selected_strategy_code": None,
        "selected_score": 0,
        "selection_reason": "",
    }

    for code in try_order:
        signal, partial = _evaluate_catalog_strategy(
            code,
            df,
            timeframe,
            option_chain,
            lot_size,
            instrument_key,
            tick=tick,
            underlying=underlying,
            params=params,
            skip_session=skip_session,
            enriched=enriched,
        )
        if signal:
            ranking = next(
                (r for r in rankings if r["strategy_id"] == STRATEGY_CATALOG[code]["id"]),
                {},
            )
            selection.update(partial)
            selection["selected_score"] = ranking.get("score", 0)
            if not selection.get("selection_reason"):
                selection["selection_reason"] = ranking.get("reason", STRATEGY_CATALOG[code]["description"])
            return signal, selection

    if try_order:
        code = try_order[0]
        selection["selected_strategy"] = STRATEGY_CATALOG[code]["id"]
        selection["selected_strategy_code"] = code
        selection["selected_label"] = STRATEGY_CATALOG[code]["label"]
    selection["selection_reason"] = selection.get("selection_reason") or "No setup on enabled strategies"
    return None, selection


def registry_for_api(strategy_family: str = "adaptive") -> list[dict[str, Any]]:
    if strategy_family == "smc":
        _, _, list_smc = _smc_registry()
        return list_smc()
    if strategy_family == "battle":
        from trading_shared.strategies.scalping_desk.battle_tested_scalp import list_battle_strategies

        return list_battle_strategies()
    adaptive = list_strategies()
    _, _, list_smc = _smc_registry()
    return adaptive + list_smc()


def all_strategy_families() -> list[dict[str, str]]:
    return [
        {"id": "battle", "label": "Battle-Tested Scalp (v5)"},
        {"id": "adaptive", "label": "AI Adaptive Scalp (v4)"},
        {"id": "smc", "label": "SMC Scalping Engine"},
    ]


def enabled_codes_for_config(config: dict[str, Any], instrument_key: str) -> list[str]:
    return enabled_codes(config, instrument_key)
