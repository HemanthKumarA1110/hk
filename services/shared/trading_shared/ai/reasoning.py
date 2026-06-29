"""Generate human-readable AI reasoning for decisions."""

from __future__ import annotations

from trading_shared.ai.types import AIDecisionResult, DecisionAction, FeatureVector, MarketRegime


def build_reasoning(
    action: DecisionAction,
    score: float,
    threshold: float,
    regime: MarketRegime,
    features: FeatureVector,
    signal: dict,
) -> list[str]:
    lines: list[str] = [
        f"AI score {score:.1f}/100 vs threshold {threshold:.0f}.",
        f"Market regime: {regime.value.replace('_', ' ')}.",
        f"Strategy engine score: {features.strategy_score:.0f} ({signal.get('engine', 'unknown')}).",
    ]

    top_features = sorted(features.to_dict().items(), key=lambda x: x[1], reverse=True)[:3]
    for name, value in top_features:
        if name == "strategy_score":
            continue
        lines.append(f"Strong {name.replace('_', ' ')} reading: {value:.0f}/100.")

    passed = [c for c in signal.get("confirmations", []) if c.get("passed")]
    if passed:
        names = ", ".join(c["name"] for c in passed[:4])
        lines.append(f"Strategy confirmations passed: {names}.")

    if action == DecisionAction.ENTER:
        lines.append(f"Recommendation: ENTER {signal.get('side')} with SL {signal.get('stoploss')} and target {signal.get('targets', [None])[0]}.")
    elif action == DecisionAction.AVOID:
        lines.append("Recommendation: AVOID — edge insufficient after AI risk overlay.")
    elif action == DecisionAction.EXIT:
        lines.append("Recommendation: EXIT — score deteriorated below exit threshold.")
    elif action == DecisionAction.SCALE_IN:
        lines.append("Recommendation: SCALE IN — moderate conviction; add with reduced size.")
    elif action == DecisionAction.PARTIAL_BOOK:
        lines.append("Recommendation: PARTIAL BOOK — lock profits on portion of position.")
    elif action == DecisionAction.HOLD:
        lines.append("Recommendation: HOLD — monitor for regime change.")

    rr = signal.get("risk_reward")
    if rr:
        lines.append(f"Risk/reward ratio: {rr}:1.")

    return lines
