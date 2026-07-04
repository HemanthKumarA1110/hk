"""Unified scalping strategy catalog with stable reference codes.

Use strategy codes (e.g. SCALP-BT-001) when requesting changes to a specific strategy.
New strategies are added here — codes are never reused.
"""

from __future__ import annotations

from typing import Any

CATALOG_VERSION = 1

# code -> metadata (immutable reference codes)
STRATEGY_CATALOG: dict[str, dict[str, Any]] = {
    "SCALP-BT-001": {
        "code": "SCALP-BT-001",
        "id": "ema_crossover_rsi",
        "family": "battle",
        "label": "EMA Crossover + RSI",
        "description": "Best Nifty/BankNifty consistency — 1:2 RRR, session-filtered",
        "instruments": ["nifty50", "banknifty"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "RANGING"],
    },
    "SCALP-BT-002": {
        "code": "SCALP-BT-002",
        "id": "orb_breakout",
        "family": "battle",
        "label": "ORB Breakout",
        "description": "Bank Nifty opening-range breakout — higher P&L",
        "instruments": ["banknifty"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"],
    },
    "SCALP-AD-001": {
        "code": "SCALP-AD-001",
        "id": "momentum_burst",
        "family": "adaptive",
        "label": "Momentum Burst",
        "description": "Volume spike + EMA alignment momentum entries",
        "instruments": ["nifty50", "banknifty"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"],
    },
    "SCALP-AD-002": {
        "code": "SCALP-AD-002",
        "id": "vwap_bounce",
        "family": "adaptive",
        "label": "VWAP Bounce",
        "description": "Mean-reversion off VWAP in ranging markets",
        "instruments": ["nifty50", "banknifty"],
        "best_regimes": ["RANGING", "LOW_VOLATILITY"],
    },
    "SCALP-AD-003": {
        "code": "SCALP-AD-003",
        "id": "trend_follow",
        "family": "adaptive",
        "label": "Trend Follow",
        "description": "EMA stack trend continuation",
        "instruments": ["nifty50", "banknifty"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN"],
    },
    "SCALP-AD-004": {
        "code": "SCALP-AD-004",
        "id": "volume_breakout",
        "family": "adaptive",
        "label": "Volume Breakout",
        "description": "High-volatility range expansion breakouts",
        "instruments": ["nifty50", "banknifty"],
        "best_regimes": ["HIGH_VOLATILITY"],
    },
    "SCALP-SMC-001": {
        "code": "SCALP-SMC-001",
        "id": "smc_fvg_ob_bos",
        "family": "smc",
        "label": "SMC FVG + OB + BOS",
        "description": "15m bias · 5m BOS · OB/FVG retest · 1m rejection",
        "instruments": ["nifty50", "banknifty"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN"],
    },
    "SCALP-SMC-002": {
        "code": "SCALP-SMC-002",
        "id": "smc_liquidity_sweep",
        "family": "smc",
        "label": "SMC Liquidity Sweep",
        "description": "Equal highs/lows sweep · M/W pattern · structure shift",
        "instruments": ["nifty50", "banknifty"],
        "best_regimes": ["RANGING", "HIGH_VOLATILITY"],
    },
    "SCALP-SMC-003": {
        "code": "SCALP-SMC-003",
        "id": "smc_orb_fvg",
        "family": "smc",
        "label": "SMC ORB + FVG",
        "description": "Opening range breakout · FVG pullback continuation",
        "instruments": ["nifty50", "banknifty"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"],
    },
}

_ID_TO_CODE: dict[str, str] = {meta["id"]: code for code, meta in STRATEGY_CATALOG.items()}


def code_for_id(strategy_id: str) -> str | None:
    return _ID_TO_CODE.get(strategy_id)


def catalog_entry(code: str) -> dict[str, Any] | None:
    return STRATEGY_CATALOG.get(code)


def catalog_for_instrument(instrument_key: str) -> list[dict[str, Any]]:
    """All catalog entries supported on this instrument."""
    return [
        dict(meta)
        for meta in STRATEGY_CATALOG.values()
        if instrument_key in meta.get("instruments", [])
    ]


def default_strategy_settings(instrument_key: str) -> dict[str, dict[str, Any]]:
    """Default: battle strategies enabled in paper mode; others off."""
    settings: dict[str, dict[str, Any]] = {}
    for meta in catalog_for_instrument(instrument_key):
        code = meta["code"]
        enabled = code in ("SCALP-BT-001", "SCALP-BT-002", "SCALP-AD-003", "SCALP-AD-004")
        if instrument_key == "nifty50" and code == "SCALP-BT-002":
            enabled = False
        if instrument_key == "banknifty" and code == "SCALP-AD-003":
            enabled = False
        settings[code] = {"enabled": enabled, "execution_mode": "paper"}
    return settings


def merge_strategy_settings(config: dict[str, Any], instrument_key: str) -> dict[str, dict[str, Any]]:
    """Merge saved settings with catalog defaults (handles newly added strategies)."""
    defaults = default_strategy_settings(instrument_key)
    saved = config.get("strategy_settings") or {}
    merged = dict(defaults)
    for code, meta in saved.items():
        if code not in STRATEGY_CATALOG:
            continue
        if instrument_key not in STRATEGY_CATALOG[code].get("instruments", []):
            continue
        entry = dict(defaults.get(code, {"enabled": False, "execution_mode": "paper"}))
        if isinstance(meta, dict):
            entry.update({k: meta[k] for k in ("enabled", "execution_mode") if k in meta})
        merged[code] = entry
    return merged


def normalize_desk_config(config: dict[str, Any], instrument_key: str) -> dict[str, Any]:
    """Ensure strategy_settings and legacy fields stay in sync."""
    cfg = dict(config)
    cfg["strategy_settings"] = merge_strategy_settings(cfg, instrument_key)
    cfg["catalog_version"] = CATALOG_VERSION

    fixed_code = cfg.get("fixed_strategy_code")
    fixed_id = cfg.get("fixed_strategy_id")
    if fixed_code and fixed_code in STRATEGY_CATALOG:
        cfg["fixed_strategy_id"] = STRATEGY_CATALOG[fixed_code]["id"]
        cfg["strategy_family"] = STRATEGY_CATALOG[fixed_code]["family"]
    elif fixed_id and not fixed_code:
        cfg["fixed_strategy_code"] = code_for_id(fixed_id)

    enabled = [c for c, s in cfg["strategy_settings"].items() if s.get("enabled")]
    if enabled and cfg.get("strategy_mode") == "manual":
        pick = cfg.get("fixed_strategy_code") or enabled[0]
        if pick in STRATEGY_CATALOG:
            cfg["fixed_strategy_code"] = pick
            cfg["fixed_strategy_id"] = STRATEGY_CATALOG[pick]["id"]
            cfg["strategy_family"] = STRATEGY_CATALOG[pick]["family"]
    return cfg


def enabled_codes(config: dict[str, Any], instrument_key: str) -> list[str]:
    settings = merge_strategy_settings(config, instrument_key)
    return [code for code, s in settings.items() if s.get("enabled")]


def strategy_setting(config: dict[str, Any], code: str, instrument_key: str) -> dict[str, Any]:
    return merge_strategy_settings(config, instrument_key).get(
        code, {"enabled": False, "execution_mode": "paper"}
    )


def resolve_strategy_code(
    *,
    selection: dict[str, Any] | None = None,
    signal: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> str | None:
    if selection and selection.get("selected_strategy_code"):
        return selection["selected_strategy_code"]
    sid = None
    if signal:
        sid = signal.get("strategy_id") or (signal.get("indicators") or {}).get("strategy_id")
    if not sid and selection:
        sid = selection.get("selected_strategy")
    if sid:
        return code_for_id(str(sid))
    if config:
        return config.get("fixed_strategy_code") or code_for_id(config.get("fixed_strategy_id") or "")
    return None


def catalog_for_api(
    instrument_key: str,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Catalog entries with current enabled/execution settings for the UI."""
    settings = merge_strategy_settings(config or {}, instrument_key)
    rows = []
    for meta in catalog_for_instrument(instrument_key):
        code = meta["code"]
        s = settings.get(code, {"enabled": False, "execution_mode": "paper"})
        rows.append(
            {
                **meta,
                "enabled": bool(s.get("enabled")),
                "execution_mode": s.get("execution_mode", "paper"),
            }
        )
    return rows
