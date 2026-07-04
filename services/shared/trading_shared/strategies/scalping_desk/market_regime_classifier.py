"""
Market regime classifier for Nifty / Bank Nifty scalping.

Deterministic implementation of the AI regime prompt; template available for
LLM extensions via `format_regime_classifier_prompt`.
"""

from __future__ import annotations

from typing import Any

from trading_shared.ai.types import MarketRegime

REGIME_CLASSIFIER_PROMPT = """Market regime classifier:
Classify today's market regime for Nifty/BankNifty scalping. Use the following inputs:

- VIX level: {VIX}
- Nifty 5m ATR(14): {ATR}
- BankNifty 5m ATR(14): {BNF_ATR}
- Advance/Decline ratio (NSE): {AD_RATIO}
- FII net cash (if available): {FII_NET}
- Global cues: SGX Nifty {SGX_CHANGE}%, Dow futures {DOW_CHANGE}%

Classify regime as one of:
1. TRENDING_BULL — clear uptrend, buy dips
2. TRENDING_BEAR — clear downtrend, sell rallies
3. RANGE_BOUND — chop, avoid or trade range extremes only
4. HIGH_VOLATILITY — VIX > 20 or ATR spike, widen SL by 30%, reduce size
5. EVENT_DRIVEN — news/expiry distortion, avoid scalping

Output JSON:
{{"regime":"TRENDING_BULL|TRENDING_BEAR|RANGE_BOUND|HIGH_VOLATILITY|EVENT_DRIVEN","confidence":0,"adjustments":{{"sl_multiplier":1.0,"size_multiplier":1.0,"allowed_directions":"both|long_only|short_only|none"}},"summary":"<20 words"}}"""

ATR_BASELINE_5M = {
    "nifty": 12.0,
    "banknifty": 40.0,
}

DEFAULT_ADJUSTMENTS: dict[str, Any] = {
    "sl_multiplier": 1.0,
    "size_multiplier": 1.0,
    "allowed_directions": "both",
}


def format_regime_classifier_prompt(
    *,
    vix: float,
    atr: float,
    bnf_atr: float,
    ad_ratio: float,
    fii_net: float | None,
    sgx_change: float,
    dow_change: float,
) -> str:
    fii = "n/a" if fii_net is None else round(fii_net, 0)
    return REGIME_CLASSIFIER_PROMPT.format(
        VIX=round(vix, 2),
        ATR=round(atr, 2),
        BNF_ATR=round(bnf_atr, 2),
        AD_RATIO=round(ad_ratio, 3),
        FII_NET=fii,
        SGX_CHANGE=round(sgx_change, 3),
        DOW_CHANGE=round(dow_change, 3),
    )


def _atr_spike(atr: float, baseline: float) -> bool:
    return baseline > 0 and atr >= baseline * 1.35


def map_regime_to_legacy(scalp_regime: str) -> str:
    """Map scalp regime labels to legacy MarketRegime values used by strategy picker."""
    mapping = {
        "TRENDING_BULL": MarketRegime.TRENDING_UP.value,
        "TRENDING_BEAR": MarketRegime.TRENDING_DOWN.value,
        "RANGE_BOUND": MarketRegime.RANGING.value,
        "HIGH_VOLATILITY": MarketRegime.HIGH_VOLATILITY.value,
        "EVENT_DRIVEN": MarketRegime.HIGH_VOLATILITY.value,
    }
    return mapping.get(str(scalp_regime).upper(), MarketRegime.RANGING.value)


def regime_allows_signal(result: dict[str, Any], signal_type: str | None) -> bool:
    """Return False when regime blocks the signal direction."""
    adj = result.get("adjustments") or {}
    allowed = str(adj.get("allowed_directions") or "both").lower()
    if allowed == "none":
        return False
    st = str(signal_type or "").upper()
    if allowed == "long_only" and st == "PUT":
        return False
    if allowed == "short_only" and st == "CALL":
        return False
    return True


def apply_regime_to_targets(targets: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Widen/tighten stop points per regime adjustments."""
    mult = float((result.get("adjustments") or {}).get("sl_multiplier") or 1.0)
    if mult == 1.0:
        return targets
    out = dict(targets)
    stop_pts = round(float(out.get("stop_pts") or 0) * mult, 2)
    out["stop_pts"] = stop_pts
    out["stop_inr"] = round(stop_pts * float(out.get("lot_size") or 1), 2) if out.get("lot_size") else out.get("stop_inr")
    if out.get("premium_stop") is not None:
        out["premium_stop"] = round(float(out["premium_stop"]) * mult, 2)
    note = f"Regime SL ×{mult:.2f}"
    out["reason"] = f"{out.get('reason', '')} · {note}".strip(" ·")
    out["regime_sl_multiplier"] = mult
    return out


def apply_regime_to_position_size(position_size: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Scale lots down when regime demands reduced size."""
    mult = float((result.get("adjustments") or {}).get("size_multiplier") or 1.0)
    if mult >= 1.0 or position_size.get("action") != "TRADE":
        return position_size
    out = dict(position_size)
    raw = int(out.get("lots") or 0)
    scaled = max(1, int(raw * mult)) if raw > 0 else 0
    if scaled < 1:
        return {
            **out,
            "action": "HALT",
            "lots": 0,
            "capital_at_risk": 0,
            "reason": "regime size multiplier reduced size below one lot",
        }
    if scaled != raw:
        risk_per_lot = float(out.get("risk_per_lot_inr") or 0)
        out["lots"] = scaled
        out["capital_at_risk"] = round(scaled * risk_per_lot, 2) if risk_per_lot else out.get("capital_at_risk")
        out["reason"] = f"{out.get('reason', '')} · regime size ×{mult:.2f}".strip(" ·")
        out["regime_size_multiplier"] = mult
    return out


def classify_market_regime(
    *,
    vix: float,
    nifty_atr: float,
    banknifty_atr: float,
    ad_ratio: float,
    fii_net: float | None = None,
    sgx_change: float = 0.0,
    dow_change: float = 0.0,
    direction: str = "neutral",
    trend_strength: float = 0.0,
    spot_change_pct: float = 0.0,
    is_expiry: bool = False,
    volume_ratio: float = 1.0,
) -> dict[str, Any]:
    """
    Classify intraday scalp regime from macro + micro inputs.

    Returns JSON-shaped dict with regime, confidence (0–100), adjustments, summary, prompt.
    """
    prompt = format_regime_classifier_prompt(
        vix=vix,
        atr=nifty_atr,
        bnf_atr=banknifty_atr,
        ad_ratio=ad_ratio,
        fii_net=fii_net,
        sgx_change=sgx_change,
        dow_change=dow_change,
    )

    nifty_spike = _atr_spike(nifty_atr, ATR_BASELINE_5M["nifty"])
    bnf_spike = _atr_spike(banknifty_atr, ATR_BASELINE_5M["banknifty"])
    atr_spike = nifty_spike or bnf_spike
    extreme_globals = abs(sgx_change) >= 1.0 or abs(dow_change) >= 1.2
    vix_high = vix > 20.0
    vix_extreme = vix > 25.0

    bull_votes = 0
    bear_votes = 0
    if sgx_change >= 0.25:
        bull_votes += 1
    elif sgx_change <= -0.25:
        bear_votes += 1
    if dow_change >= 0.2:
        bull_votes += 1
    elif dow_change <= -0.2:
        bear_votes += 1
    if ad_ratio >= 1.2:
        bull_votes += 1
    elif ad_ratio <= 0.82:
        bear_votes += 1
    if fii_net is not None:
        if fii_net >= 500:
            bull_votes += 1
        elif fii_net <= -500:
            bear_votes += 1
    if direction == "up" or spot_change_pct >= 0.35:
        bull_votes += 1
    elif direction == "down" or spot_change_pct <= -0.35:
        bear_votes += 1
    if trend_strength >= 0.06:
        if direction == "up":
            bull_votes += 1
        elif direction == "down":
            bear_votes += 1

    # 1) Event-driven — expiry or distorted session
    if is_expiry and (vix_high or atr_spike or extreme_globals):
        return {
            "regime": "EVENT_DRIVEN",
            "confidence": 88,
            "adjustments": {"sl_multiplier": 1.0, "size_multiplier": 0.0, "allowed_directions": "none"},
            "summary": "Expiry session distortion — avoid scalping today",
            "prompt": prompt,
            "legacy_regime": map_regime_to_legacy("EVENT_DRIVEN"),
            "signals": {"is_expiry": True, "vix": vix, "atr_spike": atr_spike},
        }
    if extreme_globals and (vix_extreme or abs(sgx_change) >= 1.5):
        return {
            "regime": "EVENT_DRIVEN",
            "confidence": 82,
            "adjustments": {"sl_multiplier": 1.0, "size_multiplier": 0.0, "allowed_directions": "none"},
            "summary": "Extreme global gap — news-driven, skip scalps",
            "prompt": prompt,
            "legacy_regime": map_regime_to_legacy("EVENT_DRIVEN"),
            "signals": {"extreme_globals": True},
        }

    # 2) High volatility
    if vix_high or atr_spike:
        conf = 70 + (10 if vix_high and atr_spike else 0) + (8 if vix > 22 else 0)
        summary = "Elevated vol — widen SL 30%, cut size"
        if vix_high and not atr_spike:
            summary = "VIX above 20 — widen SL, reduce size"
        elif atr_spike and not vix_high:
            summary = "5m ATR spike — widen SL 30%, half size"
        return {
            "regime": "HIGH_VOLATILITY",
            "confidence": min(conf, 95),
            "adjustments": {"sl_multiplier": 1.3, "size_multiplier": 0.7, "allowed_directions": "both"},
            "summary": summary,
            "prompt": prompt,
            "legacy_regime": map_regime_to_legacy("HIGH_VOLATILITY"),
            "signals": {"vix_high": vix_high, "atr_spike": atr_spike},
        }

    # 3) Trending
    if bull_votes >= 4 and bull_votes > bear_votes + 1:
        return {
            "regime": "TRENDING_BULL",
            "confidence": min(55 + bull_votes * 6, 92),
            "adjustments": {"sl_multiplier": 1.0, "size_multiplier": 1.0, "allowed_directions": "long_only"},
            "summary": "Uptrend day — buy dips, calls preferred",
            "prompt": prompt,
            "legacy_regime": map_regime_to_legacy("TRENDING_BULL"),
            "signals": {"bull_votes": bull_votes, "bear_votes": bear_votes},
        }
    if bear_votes >= 4 and bear_votes > bull_votes + 1:
        return {
            "regime": "TRENDING_BEAR",
            "confidence": min(55 + bear_votes * 6, 92),
            "adjustments": {"sl_multiplier": 1.0, "size_multiplier": 1.0, "allowed_directions": "short_only"},
            "summary": "Downtrend day — sell rallies, puts preferred",
            "prompt": prompt,
            "legacy_regime": map_regime_to_legacy("TRENDING_BEAR"),
            "signals": {"bull_votes": bull_votes, "bear_votes": bear_votes},
        }

    # 4) Range-bound chop
    range_like = 0.85 <= ad_ratio <= 1.15 and abs(spot_change_pct) < 0.45 and trend_strength < 0.05
    if range_like or (bull_votes <= 2 and bear_votes <= 2):
        chop = volume_ratio < 1.1 and abs(spot_change_pct) < 0.3
        return {
            "regime": "RANGE_BOUND",
            "confidence": 68 if range_like else 58,
            "adjustments": {
                "sl_multiplier": 1.0,
                "size_multiplier": 0.85 if chop else 1.0,
                "allowed_directions": "both",
            },
            "summary": "Choppy range — fade extremes only, tight filters",
            "prompt": prompt,
            "legacy_regime": map_regime_to_legacy("RANGE_BOUND"),
            "signals": {"bull_votes": bull_votes, "bear_votes": bear_votes},
        }

    # Weak lean fallback
    if bull_votes > bear_votes:
        return {
            "regime": "TRENDING_BULL",
            "confidence": 52,
            "adjustments": dict(DEFAULT_ADJUSTMENTS),
            "summary": "Mild bullish bias — selective long setups",
            "prompt": prompt,
            "legacy_regime": map_regime_to_legacy("TRENDING_BULL"),
            "signals": {"bull_votes": bull_votes, "bear_votes": bear_votes},
        }
    if bear_votes > bull_votes:
        return {
            "regime": "TRENDING_BEAR",
            "confidence": 52,
            "adjustments": dict(DEFAULT_ADJUSTMENTS),
            "summary": "Mild bearish bias — selective short setups",
            "prompt": prompt,
            "legacy_regime": map_regime_to_legacy("TRENDING_BEAR"),
            "signals": {"bull_votes": bull_votes, "bear_votes": bear_votes},
        }

    return {
        "regime": "RANGE_BOUND",
        "confidence": 50,
        "adjustments": dict(DEFAULT_ADJUSTMENTS),
        "summary": "Mixed cues — trade small, wait for clarity",
        "prompt": prompt,
        "legacy_regime": map_regime_to_legacy("RANGE_BOUND"),
        "signals": {"bull_votes": bull_votes, "bear_votes": bear_votes},
    }


def classify_from_market_context(
    *,
    instrument_key: str,
    market_ctx: dict[str, Any] | None = None,
    macro_inputs: dict[str, Any] | None = None,
    is_expiry: bool = False,
) -> dict[str, Any]:
    """Build classifier inputs from desk market context + optional macro overrides."""
    ctx = market_ctx or {}
    macro = macro_inputs or {}

    inst = instrument_key.lower()
    ctx_atr = float(ctx.get("atr") or 0)
    if inst == "banknifty":
        nifty_atr = float(macro.get("nifty_atr") or macro.get("atr") or ATR_BASELINE_5M["nifty"])
        banknifty_atr = float(macro.get("banknifty_atr") or ctx_atr or ATR_BASELINE_5M["banknifty"])
    else:
        nifty_atr = float(macro.get("nifty_atr") or ctx_atr or ATR_BASELINE_5M["nifty"])
        banknifty_atr = float(macro.get("banknifty_atr") or macro.get("bnf_atr") or ATR_BASELINE_5M["banknifty"])

    fii_raw = macro.get("fii_net")
    fii_net = None if fii_raw is None or fii_raw == "" else float(fii_raw)

    return classify_market_regime(
        vix=float(macro.get("vix") or ctx.get("vix") or 15.0),
        nifty_atr=nifty_atr,
        banknifty_atr=banknifty_atr,
        ad_ratio=float(macro.get("ad_ratio") or ctx.get("ad_ratio") or 1.0),
        fii_net=fii_net,
        sgx_change=float(macro.get("sgx_change") or ctx.get("sgx_change") or 0.0),
        dow_change=float(macro.get("dow_change") or ctx.get("dow_change") or 0.0),
        direction=str(ctx.get("direction") or "neutral"),
        trend_strength=float(ctx.get("trend_strength") or 0.0),
        spot_change_pct=float(ctx.get("spot_change_pct") or 0.0),
        is_expiry=bool(is_expiry or macro.get("is_expiry")),
        volume_ratio=float(ctx.get("volume_ratio") or 1.0),
    )


def merge_regime_into_context(
    market_ctx: dict[str, Any],
    regime_result: dict[str, Any],
) -> dict[str, Any]:
    """Attach scalp regime fields to market_context for API / AI layers."""
    out = dict(market_ctx)
    out["scalp_regime"] = regime_result.get("regime")
    out["regime_confidence"] = regime_result.get("confidence")
    out["regime_summary"] = regime_result.get("summary")
    out["regime_adjustments"] = regime_result.get("adjustments")
    out["regime"] = regime_result.get("legacy_regime") or map_regime_to_legacy(str(regime_result.get("regime", "")))
    return out
