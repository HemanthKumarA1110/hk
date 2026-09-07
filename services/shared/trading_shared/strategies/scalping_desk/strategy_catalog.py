"""Unified scalping strategy catalog with stable reference codes.

Use strategy codes (e.g. SCALP-BT-001) when requesting changes to a specific strategy.
Nifty 50 and Bank Nifty use separate catalog codes (shared logic via strategy id).
New strategies are added here — codes are never reused.
"""

from __future__ import annotations

from typing import Any

CATALOG_VERSION = 27

STRATEGY_CATALOG: dict[str, dict[str, Any]] = {
    "SCALP-BT-002": {
        "code": "SCALP-BT-002",
        "id": "orb_breakout",
        "family": "battle",
        "label": "ORB Breakout (Bank Nifty)",
        "description": "Bank Nifty ORB — only when opening range is 120–200 pts (60d Angel One tuned)",
        "instruments": ["banknifty"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"],
    },
    "SCALP-BT-003": {
        "code": "SCALP-BT-003",
        "id": "ema_crossover_rsi",
        "family": "battle",
        "label": "EMA Crossover + RSI (Bank Nifty)",
        "description": "Bank Nifty EMA 8/21 + RSI — CALL 53–60 / PUT 38–46, VWAP optional, stop 75 / target 150",
        "instruments": ["banknifty"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "RANGING"],
    },
    "SCALP-BT-004": {
        "code": "SCALP-BT-004",
        "id": "orb_breakout",
        "family": "battle",
        "label": "ORB Breakout",
        "description": "Nifty 50 ORB — OR 45–80 pts, ~4pt buffer, EMA8/20, ATR momentum, stop 6 / target 12",
        "instruments": ["nifty50"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"],
        "clone_of": "SCALP-BT-002",
    },
    "SCALP-AD-002": {
        "code": "SCALP-AD-002",
        "id": "vwap_bounce",
        "family": "adaptive",
        "label": "VWAP Bounce",
        "description": "Nifty 50 VWAP bounce — 0.20% band, CALL prev RSI<42, stop~0.70× / target~0.20× profile, hold 12 (60d retuned)",
        "instruments": ["nifty50"],
        "best_regimes": ["RANGING", "LOW_VOLATILITY"],
    },
    "SCALP-AD-006": {
        "code": "SCALP-AD-006",
        "id": "vwap_bounce",
        "family": "adaptive",
        "label": "VWAP Bounce (Bank Nifty)",
        "description": "Bank Nifty VWAP mean-reversion — near 0.25%, CALL RSI 43–55, PUT 44–58, hold 6 (60d retuned)",
        "instruments": ["banknifty"],
        "best_regimes": ["RANGING", "LOW_VOLATILITY"],
        "clone_of": "SCALP-AD-002",
    },
    "SCALP-SMC-003": {
        "code": "SCALP-SMC-003",
        "id": "smc_orb_fvg",
        "family": "smc",
        "label": "SMC ORB + FVG",
        "description": "Nifty 50 · ORB+FVG · OR≥40 · vol≥1.15x · pad 0.20% · scan 2 · hold 6 (v27)",
        "instruments": ["nifty50"],
        "best_regimes": ["TRENDING_UP", "TRENDING_DOWN", "HIGH_VOLATILITY"],
    },
}

# Legacy shared codes saved on Bank Nifty desks before catalog v2.
# Mappings to removed Bank Nifty clones (AD-005/007/008, SMC-004/005/006) are intentionally omitted
# or remapped to remaining Bank strategies.
BANK_NIFTY_LEGACY_CODE_MAP: dict[str, str] = {
    "SCALP-BT-001": "SCALP-BT-003",
    "SCALP-AD-001": "SCALP-AD-006",
    "SCALP-AD-002": "SCALP-AD-006",
    "SCALP-AD-005": "SCALP-AD-006",
    "SCALP-SMC-003": "SCALP-BT-003",
    "SCALP-SMC-006": "SCALP-BT-003",
}

# Removed Nifty catalog codes → remaining default on that desk.
NIFTY_REMOVED_CODE_MAP: dict[str, str] = {
    "SCALP-BT-001": "SCALP-AD-002",
    "SCALP-AD-001": "SCALP-AD-002",
    "SCALP-AD-003": "SCALP-AD-002",
    "SCALP-AD-004": "SCALP-AD-002",
    "SCALP-SMC-001": "SCALP-SMC-003",
    "SCALP-SMC-002": "SCALP-SMC-003",
}

_ID_TO_CODE: dict[str, str] = {meta["id"]: code for code, meta in STRATEGY_CATALOG.items()}


def default_fixed_strategy_code(instrument_key: str) -> str:
    return "SCALP-BT-003" if instrument_key == "banknifty" else "SCALP-AD-002"


def code_for_id(strategy_id: str, instrument_key: str | None = None) -> str | None:
    if instrument_key:
        for code, meta in STRATEGY_CATALOG.items():
            if meta["id"] == strategy_id and instrument_key in meta.get("instruments", []):
                return code
        return None
    return _ID_TO_CODE.get(strategy_id)


def migrate_bank_strategy_code(code: str, instrument_key: str) -> str:
    if instrument_key == "banknifty":
        return BANK_NIFTY_LEGACY_CODE_MAP.get(code, code)
    if instrument_key == "nifty50":
        return NIFTY_REMOVED_CODE_MAP.get(code, code)
    return code


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
    """Default enablement for manual multi-select (auto mode monitors the full catalog)."""
    settings: dict[str, dict[str, Any]] = {}
    for meta in catalog_for_instrument(instrument_key):
        # All catalog strategies on by default for continuous multi-monitor.
        settings[meta["code"]] = {"enabled": True, "execution_mode": "live"}
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
        entry = dict(defaults.get(code, {"enabled": False, "execution_mode": "live"}))
        if isinstance(meta, dict):
            entry.update({k: meta[k] for k in ("enabled",) if k in meta})
            entry["execution_mode"] = "live"
        merged[code] = entry
    return merged


def normalize_desk_config(config: dict[str, Any], instrument_key: str) -> dict[str, Any]:
    """Ensure strategy_settings and legacy fields stay in sync."""
    from trading_shared.strategies.scalping_desk.orb_breakout_tuning import (
        ORB_BREAKOUT_BANK_DEFAULTS,
        ORB_BREAKOUT_NIFTY_DEFAULTS,
    )
    from trading_shared.strategies.scalping_desk.ema_crossover_tuning import EMA_CROSSOVER_BANK_DEFAULTS
    from trading_shared.strategies.scalping_desk.vwap_bounce_tuning import (
        VWAP_BOUNCE_BANK_DEFAULTS,
        VWAP_BOUNCE_NIFTY_DEFAULTS,
    )
    from trading_shared.strategies.scalping_desk.smc_orb_fvg_tuning import (
        SMC_ORB_FVG_NIFTY_DEFAULTS,
    )

    cfg = dict(config)
    prev_version = int(cfg.get("catalog_version") or 0)
    cfg["strategy_settings"] = merge_strategy_settings(cfg, instrument_key)

    def _force_enable_all() -> None:
        defaults = default_strategy_settings(instrument_key)
        refreshed: dict[str, dict[str, Any]] = {}
        for code, dflt in defaults.items():
            refreshed[code] = {
                "enabled": True,
                "execution_mode": "live",
            }
        cfg["strategy_settings"] = refreshed

    if instrument_key == "banknifty":
        params = dict(cfg.get("params") or {})
        saved_orb = params.get("orb_breakout") if isinstance(params.get("orb_breakout"), dict) else {}
        saved_ema = params.get("ema_crossover") if isinstance(params.get("ema_crossover"), dict) else {}
        saved_vb = params.get("vwap_bounce") if isinstance(params.get("vwap_bounce"), dict) else {}
        if prev_version < CATALOG_VERSION:
            # Reset stale tuned params saved under older catalog versions.
            params["orb_breakout"] = dict(ORB_BREAKOUT_BANK_DEFAULTS)
            params["ema_crossover"] = dict(EMA_CROSSOVER_BANK_DEFAULTS)
            params["vwap_bounce"] = dict(VWAP_BOUNCE_BANK_DEFAULTS)
            # v17+: enable all Bank Nifty strategies for continuous multi-monitor.
            # v26: drop AD-005 / SMC-006 — re-enable remaining bank set.
            if prev_version < 26:
                _force_enable_all()
        else:
            params["orb_breakout"] = {**ORB_BREAKOUT_BANK_DEFAULTS, **saved_orb}
            params["ema_crossover"] = {**EMA_CROSSOVER_BANK_DEFAULTS, **saved_ema}
            params["vwap_bounce"] = {**VWAP_BOUNCE_BANK_DEFAULTS, **saved_vb}
        params.pop("momentum_burst", None)  # AD-005 removed
        cfg.pop("smc_params", None)  # Bank SMC-006 removed — Nifty still uses smc_params
        cfg["params"] = params
    elif instrument_key == "nifty50":
        params = dict(cfg.get("params") or {})
        saved_orb = params.get("orb_breakout") if isinstance(params.get("orb_breakout"), dict) else {}
        saved_vb = params.get("vwap_bounce") if isinstance(params.get("vwap_bounce"), dict) else {}
        saved_smc = cfg.get("smc_params") if isinstance(cfg.get("smc_params"), dict) else {}
        if prev_version < CATALOG_VERSION:
            params["orb_breakout"] = dict(ORB_BREAKOUT_NIFTY_DEFAULTS)
            params["vwap_bounce"] = dict(VWAP_BOUNCE_NIFTY_DEFAULTS)
            cfg["smc_params"] = dict(SMC_ORB_FVG_NIFTY_DEFAULTS)
            # v19+: enable remaining Nifty strategies; v20 adds BT-004 ORB; v21 retunes BT-004; v22 AD-002 vb_*; v23 SMC-003.
            if prev_version < 20:
                _force_enable_all()
        else:
            params["orb_breakout"] = {**ORB_BREAKOUT_NIFTY_DEFAULTS, **saved_orb}
            params["vwap_bounce"] = {**VWAP_BOUNCE_NIFTY_DEFAULTS, **saved_vb}
            cfg["smc_params"] = {**SMC_ORB_FVG_NIFTY_DEFAULTS, **saved_smc}
        params.pop("ema_crossover", None)  # BT-001 removed — EMA nest no longer used on Nifty desk
        cfg["params"] = params

    cfg["catalog_version"] = CATALOG_VERSION

    fixed_code = cfg.get("fixed_strategy_code")
    if fixed_code:
        fixed_code = migrate_bank_strategy_code(str(fixed_code), instrument_key)
        cfg["fixed_strategy_code"] = fixed_code
    # Drop removed / invalid fixed strategies (Bank AD-005/007/008/SMC-004/005/006; Nifty BT-001/AD-001/003/004/SMC-001/002).
    if fixed_code and (
        fixed_code not in STRATEGY_CATALOG
        or instrument_key not in STRATEGY_CATALOG[fixed_code].get("instruments", [])
    ):
        fixed_code = default_fixed_strategy_code(instrument_key)
        cfg["fixed_strategy_code"] = fixed_code
    fixed_id = cfg.get("fixed_strategy_id")
    if fixed_code and fixed_code in STRATEGY_CATALOG:
        cfg["fixed_strategy_id"] = STRATEGY_CATALOG[fixed_code]["id"]
        cfg["strategy_family"] = STRATEGY_CATALOG[fixed_code]["family"]
    elif fixed_id and not fixed_code:
        mapped = code_for_id(str(fixed_id), instrument_key)
        cfg["fixed_strategy_code"] = mapped or default_fixed_strategy_code(instrument_key)
        fixed_code = cfg["fixed_strategy_code"]
        if fixed_code in STRATEGY_CATALOG:
            cfg["fixed_strategy_id"] = STRATEGY_CATALOG[fixed_code]["id"]
            cfg["strategy_family"] = STRATEGY_CATALOG[fixed_code]["family"]
    if not cfg.get("fixed_strategy_code"):
        pick = default_fixed_strategy_code(instrument_key)
        cfg["fixed_strategy_code"] = pick
        cfg["fixed_strategy_id"] = STRATEGY_CATALOG[pick]["id"]
        cfg["strategy_family"] = STRATEGY_CATALOG[pick]["family"]

    enabled = [c for c, s in cfg["strategy_settings"].items() if s.get("enabled")]
    # Manual multi-select: keep fixed_strategy_* as display preference (first enabled if unset).
    if enabled and cfg.get("strategy_mode") == "manual":
        pick = migrate_bank_strategy_code(str(cfg.get("fixed_strategy_code") or enabled[0]), instrument_key)
        if pick not in enabled:
            pick = enabled[0]
        if pick in STRATEGY_CATALOG:
            cfg["fixed_strategy_code"] = pick
            cfg["fixed_strategy_id"] = STRATEGY_CATALOG[pick]["id"]
            cfg["strategy_family"] = STRATEGY_CATALOG[pick]["family"]
    cfg["option_execution_policy"] = "buy_only"
    if "expiry_restrictions_enabled" not in cfg:
        cfg["expiry_restrictions_enabled"] = True
    if "ai_daily_stop_enabled" not in cfg:
        cfg["ai_daily_stop_enabled"] = True
    # Full-capital sizing: drop legacy 2-lot / 95% caps on catalog migrate.
    if prev_version < 25:
        cfg["max_lots_per_trade"] = 0
        cfg["capital_utilization_pct"] = 1.0
    else:
        if cfg.get("max_lots_per_trade") is None:
            cfg["max_lots_per_trade"] = 0
        if cfg.get("capital_utilization_pct") is None:
            cfg["capital_utilization_pct"] = 1.0
    return cfg


def enabled_codes(config: dict[str, Any], instrument_key: str) -> list[str]:
    settings = merge_strategy_settings(config, instrument_key)
    return [code for code, s in settings.items() if s.get("enabled")]


def strategy_setting(config: dict[str, Any], code: str, instrument_key: str) -> dict[str, Any]:
    return merge_strategy_settings(config, instrument_key).get(
        code, {"enabled": False, "execution_mode": "live"}
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
        s = settings.get(code, {"enabled": False, "execution_mode": "live"})
        rows.append(
            {
                **meta,
                "enabled": bool(s.get("enabled")),
                "execution_mode": "live",
                "execution_policy": "buy_ce_pe",
                "entry_side": "BUY",
                "option_legs": "CE on CALL · PE on PUT",
            }
        )
    return rows
