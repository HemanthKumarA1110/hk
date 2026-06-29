"""Pick the freshest cached signal payload for an engine."""

from __future__ import annotations


def pick_fresher_signal_payload(
    desk_payload: dict | None,
    orchestrator_payload: dict,
    *,
    fallback_source: str = "orchestrator",
) -> dict:
    desk = desk_payload or {}
    cached = orchestrator_payload or {}
    desk_signals = desk.get("signals") or []
    cached_signals = cached.get("signals") or []

    if desk_signals and not cached_signals:
        return desk
    if cached_signals and not desk_signals:
        return {**desk, **cached, "signals": cached_signals, "source": fallback_source}
    if not desk_signals and not cached_signals:
        return {**desk, **cached, "signals": [], "source": fallback_source}

    desk_at = str(desk.get("generated_at") or "")
    cached_at = str(cached.get("generated_at") or "")
    if cached_at >= desk_at:
        return {**desk, **cached, "signals": cached_signals, "source": fallback_source}
    return desk
