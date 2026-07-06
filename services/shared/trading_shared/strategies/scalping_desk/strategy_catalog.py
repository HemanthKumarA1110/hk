"""Unified scalping strategy catalog with stable reference codes.

Use strategy codes (e.g. SCALP-BT-001) when requesting changes to a specific strategy.
Nifty 50 and Bank Nifty use separate catalog codes (shared logic via strategy id).
New strategies are added here — codes are never reused.
"""

from __future__ import annotations

from typing import Any

CATALOG_VERSION = 9
STRATEGY_CATALOG: dict[str, dict[str, Any]] = {
    "SCALP-BT-001": {
        "code": "SCALP-BT-001",
        "id": "ema_crossover_rsi",
        "family": "battle",
        "label": "EMA Crossover + RSI",
        "description": "Nifty 50 EMA 9/21 + RSI — buy CE/PE only, 1:2 RRR, session-filtered",
        "instruments": ["nifty50"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "RANGING"],
    },
    "SCALP-BT-002": {
        "code": "SCALP-BT-002",
        "id": "orb_breakout",
        "family": "battle",
        "label": "ORB Breakout",
        "description": "Bank Nifty ORB — only when opening range is 120–200 pts (60d Angel One tuned)",
        "instruments": ["banknifty"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"],
    },
    "SCALP-BT-003": {
        "code": "SCALP-BT-003",
        "id": "ema_crossover_rsi",
        "family": "battle",
        "label": "EMA Crossover + RSI (Bank Nifty)",
        "description": "Bank Nifty EMA 9/21 + RSI — tighter RSI bands 53–60 / 40–46 (60d tuned)",
        "instruments": ["banknifty"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "RANGING"],
        "clone_of": "SCALP-BT-001",
    },
    "SCALP-AD-001": {
        "code": "SCALP-AD-001",
        "id": "momentum_burst",
        "family": "adaptive",
        "label": "Momentum Burst",
        "description": "Nifty 50 volume spike + EMA alignment momentum entries",
        "instruments": ["nifty50"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"],
    },
    "SCALP-AD-002": {
        "code": "SCALP-AD-002",
        "id": "vwap_bounce",
        "family": "adaptive",
        "label": "VWAP Bounce",
        "description": "Nifty 50 mean-reversion off VWAP in ranging markets",
        "instruments": ["nifty50"],
        "best_regimes": ["RANGING", "LOW_VOLATILITY"],
    },
    "SCALP-AD-003": {
        "code": "SCALP-AD-003",
        "id": "trend_follow",
        "family": "adaptive",
        "label": "Trend Follow",
        "description": "Nifty 50 EMA stack trend continuation",
        "instruments": ["nifty50"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN"],
    },
    "SCALP-AD-004": {
        "code": "SCALP-AD-004",
        "id": "volume_breakout",
        "family": "adaptive",
        "label": "Volume Breakout",
        "description": "Nifty 50 high-volatility range expansion breakouts",
        "instruments": ["nifty50"],
        "best_regimes": ["HIGH_VOLATILITY"],
    },
    "SCALP-AD-005": {
        "code": "SCALP-AD-005",
        "id": "momentum_burst",
        "family": "adaptive",
        "label": "Momentum Burst (Bank Nifty)",
        "description": "Bank Nifty volume spike + EMA alignment momentum entries",
        "instruments": ["banknifty"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"],
        "clone_of": "SCALP-AD-001",
    },
    "SCALP-AD-006": {
        "code": "SCALP-AD-006",
        "id": "vwap_bounce",
        "family": "adaptive",
        "label": "VWAP Bounce (Bank Nifty)",
        "description": "Bank Nifty mean-reversion off VWAP in ranging markets",
        "instruments": ["banknifty"],
        "best_regimes": ["RANGING", "LOW_VOLATILITY"],
        "clone_of": "SCALP-AD-002",
    },
    "SCALP-AD-007": {
        "code": "SCALP-AD-007",
        "id": "trend_follow",
        "family": "adaptive",
        "label": "Trend Follow (Bank Nifty)",
        "description": "Bank Nifty EMA stack trend continuation",
        "instruments": ["banknifty"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN"],
        "clone_of": "SCALP-AD-003",
    },
    "SCALP-AD-008": {
        "code": "SCALP-AD-008",
        "id": "volume_breakout",
        "family": "adaptive",
        "label": "Volume Breakout (Bank Nifty)",
        "description": "Bank Nifty high-volatility range expansion breakouts",
        "instruments": ["banknifty"],
        "best_regimes": ["HIGH_VOLATILITY"],
        "clone_of": "SCALP-AD-004",
    },
    "SCALP-SMC-001": {
        "code": "SCALP-SMC-001",
        "id": "smc_fvg_ob_bos",
        "family": "smc",
        "label": "SMC FVG + OB + BOS",
        "description": "Nifty 50 · 15m bias · 5m BOS · OB/FVG retest · 1m rejection",
        "instruments": ["nifty50"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN"],
    },
    "SCALP-SMC-002": {
        "code": "SCALP-SMC-002",
        "id": "smc_liquidity_sweep",
        "family": "smc",
        "label": "SMC Liquidity Sweep",
        "description": "Nifty 50 · equal highs/lows sweep · M/W pattern · structure shift",
        "instruments": ["nifty50"],
        "best_regimes": ["RANGING", "HIGH_VOLATILITY"],
    },
    "SCALP-SMC-003": {
        "code": "SCALP-SMC-003",
        "id": "smc_orb_fvg",
        "family": "smc",
        "label": "SMC ORB + FVG",
        "description": "Nifty 50 · opening range breakout · FVG pullback continuation",
        "instruments": ["nifty50"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"],
    },
    "SCALP-SMC-004": {
        "code": "SCALP-SMC-004",
        "id": "smc_fvg_ob_bos",
        "family": "smc",
        "label": "SMC FVG + OB + BOS (Bank Nifty)",
        "description": "Bank Nifty · 15m bias · 5m BOS · OB/FVG retest · tuned 60d Angel One",
        "instruments": ["banknifty"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN"],
        "clone_of": "SCALP-SMC-001",
    },
    "SCALP-SMC-005": {
        "code": "SCALP-SMC-005",
        "id": "smc_liquidity_sweep",
        "family": "smc",
        "label": "SMC Liquidity Sweep (Bank Nifty)",
        "description": "Bank Nifty · equal highs/lows sweep · M/W pattern · structure shift",
        "instruments": ["banknifty"],
        "best_regimes": ["RANGING", "HIGH_VOLATILITY"],
        "clone_of": "SCALP-SMC-002",
    },
    "SCALP-SMC-006": {
        "code": "SCALP-SMC-006",
        "id": "smc_orb_fvg",
        "family": "smc",
        "label": "SMC ORB + FVG (Bank Nifty)",
        "description": "Bank Nifty · opening range breakout · FVG pullback · 60d Angel One tuned",
        "instruments": ["banknifty"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"],
        "clone_of": "SCALP-SMC-003",
    },
}

# Legacy shared codes saved on Bank Nifty desks before catalog v2.
BANK_NIFTY_LEGACY_CODE_MAP: dict[str, str] = {
    "SCALP-BT-001": "SCALP-BT-003",
    "SCALP-AD-001": "SCALP-AD-005",
    "SCALP-AD-002": "SCALP-AD-006",
    "SCALP-AD-003": "SCALP-AD-007",
    "SCALP-AD-004": "SCALP-AD-008",
    "SCALP-SMC-001": "SCALP-SMC-004",
    "SCALP-SMC-002": "SCALP-SMC-005",
    "SCALP-SMC-003": "SCALP-SMC-006",
}

_ID_TO_CODE: dict[str, str] = {meta["id"]: code for code, meta in STRATEGY_CATALOG.items()}


def default_fixed_strategy_code(instrument_key: str) -> str:
    return "SCALP-BT-003" if instrument_key == "banknifty" else "SCALP-BT-001"


def code_for_id(strategy_id: str, instrument_key: str | None = None) -> str | None:
    if instrument_key:
        for code, meta in STRATEGY_CATALOG.items():
            if meta["id"] == strategy_id and instrument_key in meta.get("instruments", []):
                return code
        return None
    return _ID_TO_CODE.get(strategy_id)


def migrate_bank_strategy_code(code: str, instrument_key: str) -> str:
    if instrument_key != "banknifty":
        return code
    return BANK_NIFTY_LEGACY_CODE_MAP.get(code, code)


def _migrate_saved_settings(saved: dict[str, Any], instrument_key: str) -> dict[str, Any]:
    if instrument_key != "banknifty":
        return saved or {}
    migrated: dict[str, Any] = {}
    for code, meta in (saved or {}).items():
        if not isinstance(meta, dict):
            continue
        new_code = BANK_NIFTY_LEGACY_CODE_MAP.get(code, code)
        entry = STRATEGY_CATALOG.get(new_code)
        if not entry or instrument_key not in entry.get("instruments", []):
            continue
        prev = migrated.get(new_code, {})
        merged = {**prev, **meta}
        if prev.get("enabled") or meta.get("enabled"):
            merged["enabled"] = True
        migrated[new_code] = merged
    return migrated


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
        if instrument_key == "banknifty":
            enabled = code in ("SCALP-BT-002", "SCALP-BT-003", "SCALP-AD-007", "SCALP-AD-008")
            if code == "SCALP-AD-007":
                enabled = False
        else:
            enabled = code in ("SCALP-BT-001", "SCALP-AD-003", "SCALP-AD-004")
        settings[code] = {"enabled": enabled, "execution_mode": "paper"}
    return settings


def merge_strategy_settings(config: dict[str, Any], instrument_key: str) -> dict[str, dict[str, Any]]:
    """Merge saved settings with catalog defaults (handles newly added strategies)."""
    defaults = default_strategy_settings(instrument_key)
    saved = _migrate_saved_settings(config.get("strategy_settings") or {}, instrument_key)
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
    from trading_shared.strategies.scalping_desk.orb_breakout_tuning import ORB_BREAKOUT_BANK_DEFAULTS
    from trading_shared.strategies.scalping_desk.ema_crossover_tuning import EMA_CROSSOVER_BANK_DEFAULTS
    from trading_shared.strategies.scalping_desk.smc_fvg_ob_bos_tuning import SMC_FVG_OB_BOS_BANK_DEFAULTS
    from trading_shared.strategies.scalping_desk.smc_orb_fvg_tuning import SMC_ORB_FVG_BANK_DEFAULTS

    cfg = dict(config)
    prev_version = int(cfg.get("catalog_version") or 0)
    cfg["strategy_settings"] = merge_strategy_settings(cfg, instrument_key)
    if instrument_key == "banknifty":
        params = dict(cfg.get("params") or {})
        saved_orb = params.get("orb_breakout") if isinstance(params.get("orb_breakout"), dict) else {}
        saved_ema = params.get("ema_crossover") if isinstance(params.get("ema_crossover"), dict) else {}
        saved_smc = cfg.get("smc_params") if isinstance(cfg.get("smc_params"), dict) else {}
        if prev_version < CATALOG_VERSION:
            # Reset stale tuned params saved under older catalog versions.
            params["orb_breakout"] = dict(ORB_BREAKOUT_BANK_DEFAULTS)
            params["ema_crossover"] = dict(EMA_CROSSOVER_BANK_DEFAULTS)
            cfg["smc_params"] = {**SMC_FVG_OB_BOS_BANK_DEFAULTS, **SMC_ORB_FVG_BANK_DEFAULTS}
        else:
            params["orb_breakout"] = {**ORB_BREAKOUT_BANK_DEFAULTS, **saved_orb}
            params["ema_crossover"] = {**EMA_CROSSOVER_BANK_DEFAULTS, **saved_ema}
            cfg["smc_params"] = {
                **SMC_FVG_OB_BOS_BANK_DEFAULTS,
                **SMC_ORB_FVG_BANK_DEFAULTS,
                **saved_smc,
            }
        cfg["params"] = params
    cfg["catalog_version"] = CATALOG_VERSION

    fixed_code = cfg.get("fixed_strategy_code")
    if fixed_code:
        fixed_code = migrate_bank_strategy_code(str(fixed_code), instrument_key)
        cfg["fixed_strategy_code"] = fixed_code
    fixed_id = cfg.get("fixed_strategy_id")
    if fixed_code and fixed_code in STRATEGY_CATALOG:
        cfg["fixed_strategy_id"] = STRATEGY_CATALOG[fixed_code]["id"]
        cfg["strategy_family"] = STRATEGY_CATALOG[fixed_code]["family"]
    elif fixed_id and not fixed_code:
        cfg["fixed_strategy_code"] = code_for_id(fixed_id, instrument_key)

    enabled = [c for c, s in cfg["strategy_settings"].items() if s.get("enabled")]
    if enabled and cfg.get("strategy_mode") == "manual":
        pick = migrate_bank_strategy_code(str(cfg.get("fixed_strategy_code") or enabled[0]), instrument_key)
        if pick in STRATEGY_CATALOG:
            cfg["fixed_strategy_code"] = pick
            cfg["fixed_strategy_id"] = STRATEGY_CATALOG[pick]["id"]
            cfg["strategy_family"] = STRATEGY_CATALOG[pick]["family"]
    cfg["option_execution_policy"] = "buy_only"
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
    instrument_key: str | None = None,
) -> str | None:
    if selection and selection.get("selected_strategy_code"):
        code = str(selection["selected_strategy_code"])
        if instrument_key:
            return migrate_bank_strategy_code(code, instrument_key)
        return code
    sid = None
    if signal:
        sid = signal.get("strategy_id") or (signal.get("indicators") or {}).get("strategy_id")
    if not sid and selection:
        sid = selection.get("selected_strategy")
    if sid:
        return code_for_id(str(sid), instrument_key)
    if config:
        code = config.get("fixed_strategy_code")
        if code and instrument_key:
            code = migrate_bank_strategy_code(str(code), instrument_key)
            return code
        return code or code_for_id(config.get("fixed_strategy_id") or "", instrument_key)
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
                "execution_policy": "buy_ce_pe",
                "entry_side": "BUY",
                "option_legs": "CE on CALL · PE on PUT",
            }
        )
    return rows
