"""
Structured trade reasoning prompts + deterministic evaluators.

Prompt templates mirror disciplined analyst checklists (entry, dynamic exit,
desk-specific add-ons, post-trade review). Deterministic functions implement
the same logic for live/paper trading without an LLM.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")

# --- Prompt #1: multi-factor entry confirmation ---
ENTRY_CONFIRMATION_PROMPT = """You are a disciplined intraday/swing trading analyst. Evaluate the signal — do NOT blindly confirm.

Signal: {strategy} · {side} @ {entry} · SL {stop} · target {target}
Last {candle_count} candles ({timeframe}), RSI={rsi}, ATR={atr}, VWAP/EMA context={indicator_context}
Index/sector: {index_context}

Score each factor (one line each):
1. Price action — fresh vs late trigger
2. Volume — genuine vs low-liquidity spike
3. Index/sector alignment WITH or AGAINST direction
4. Support/resistance inside target zone
5. ATR vs planned stop distance

Output: confidence (High/Medium/Low), recommended action (Take / Adjust / Skip), brief per-factor notes."""

# --- Prompt #2: dynamic exit ---
DYNAMIC_EXIT_PROMPT = """You manage an open trade. Original target/stop are reference only — reassess hold vs tighten vs partial vs full exit.

Entry {entry} · SL {stop} · target {target} · strategy {strategy} · held {held}
Current {current} · unrealized P&L {pnl}
Recent candles since entry provided.

Walk through: momentum · target proximity · thesis invalidation · time decay · volatility shift.
Output: assessment (Hold/Tighten/Take partial/Exit), paragraph reasoning, revised SL/target if any, confidence."""

INTRADAY_EXIT_ADDON = """Intraday checks: VWAP reclaim against position, avoid 9:15–9:30 & 3:15–3:30 erratic windows,
declining volume into move = exhaustion, hard exit by 3:15 PM."""

SWING_EXIT_ADDON = """Swing checks: daily structure break, event risk, relative weakness vs sector/Nifty,
move stop to breakeven after +1R."""

POST_TRADE_REVIEW_PROMPT = """Review closed trade: entry/exit vs original plan; 10 candles after exit.
Was exit early/late/well-timed? Was target realistic? One factor to weight differently? Pattern vs recent trades?"""


def format_entry_confirmation_prompt(**kwargs: Any) -> str:
    return ENTRY_CONFIRMATION_PROMPT.format(**kwargs)


def format_dynamic_exit_prompt(**kwargs: Any) -> str:
    return DYNAMIC_EXIT_PROMPT.format(**kwargs)


def _confidence_label(score: float) -> str:
    if score >= 75:
        return "High"
    if score >= 50:
        return "Medium"
    return "Low"


def _side_is_long(side: str) -> bool:
    return str(side).upper() in ("BUY", "CALL", "LONG")


def _atr14(df: pd.DataFrame) -> float:
    if df.empty or len(df) < 2:
        return 0.0
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([(high - low), (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    return float(tr.rolling(14, min_periods=1).mean().iloc[-1])


def _recent_momentum(df: pd.DataFrame, is_long: bool, bars: int = 8) -> tuple[str, float]:
    """Return momentum label and score 0-100."""
    if len(df) < bars + 1:
        return "insufficient data", 50.0
    tail = df.tail(bars)
    closes = tail["close"].astype(float)
    if is_long:
        up = sum(closes.iloc[i] > closes.iloc[i - 1] for i in range(1, len(closes)))
        net = float(closes.iloc[-1] - closes.iloc[0])
        if net > 0 and up >= bars * 0.55:
            return "favorable momentum", 85.0
        if net <= 0 and up < bars * 0.4:
            return "reversing", 20.0
        return "stalling", 45.0
    down = sum(closes.iloc[i] < closes.iloc[i - 1] for i in range(1, len(closes)))
    net = float(closes.iloc[0] - closes.iloc[-1])
    if net > 0 and down >= bars * 0.55:
        return "favorable momentum", 85.0
    if net <= 0 and down < bars * 0.4:
        return "reversing", 20.0
    return "stalling", 45.0


def evaluate_entry_confirmation(
    *,
    strategy: str,
    side: str,
    entry: float,
    stop: float,
    target: float | None,
    candles: pd.DataFrame,
    timeframe: str = "1m",
    rsi: float | None = None,
    atr: float | None = None,
    vwap: float | None = None,
    volume_ratio: float | None = None,
    index_trend: str | None = None,
    sector_trend: str | None = None,
) -> dict[str, Any]:
    """
    Multi-factor entry gate (prompt #1). Returns confidence, action, factor notes, and prompt text.
    """
    is_long = _side_is_long(side)
    df = candles.tail(20).copy() if candles is not None and not candles.empty else pd.DataFrame()
    if df.empty or len(df) < 5:
        return {
            "confidence": "Low",
            "confidence_score": 25,
            "action": "Skip",
            "factor_notes": ["Insufficient candle history for confirmation"],
            "prompt": format_entry_confirmation_prompt(
                strategy=strategy,
                side=side,
                entry=entry,
                stop=stop,
                target=target or "—",
                candle_count=0,
                timeframe=timeframe,
                rsi=rsi or "—",
                atr=atr or "—",
                indicator_context="n/a",
                index_context=index_trend or "unknown",
            ),
        }

    spot = float(df.iloc[-1]["close"])
    atr_val = atr if atr is not None else _atr14(df)
    rsi_val = rsi if rsi is not None else 50.0
    vol_ratio = volume_ratio if volume_ratio is not None else 1.0
    vwap_val = vwap if vwap is not None else spot

    # 1) Price action — extension from recent range midpoint
    mid = (float(df["high"].max()) + float(df["low"].min())) / 2
    extension = abs(spot - mid) / max(mid, 1) * 100
    late_trigger = extension > 0.55
    pa_note = f"{'Late/extended' if late_trigger else 'Fresh'} trigger ({extension:.2f}% from range mid)"
    pa_score = 40.0 if late_trigger else 82.0

    # 2) Volume — soft gate; strategy already filters spikes
    vol_ok = vol_ratio >= 1.05
    vol_note = f"Volume {vol_ratio:.2f}x avg — {'confirming' if vol_ok else 'light but ok'}"
    vol_score = 78.0 if vol_ok else 52.0

    # 3) Index / sector alignment
    idx = (index_trend or "").upper()
    sec = (sector_trend or "").upper()
    aligned = (is_long and idx in ("UP", "BULL", "TRENDING_UP")) or (
        not is_long and idx in ("DOWN", "BEAR", "TRENDING_DOWN")
    )
    against = (is_long and idx in ("DOWN", "BEAR", "TRENDING_DOWN")) or (
        not is_long and idx in ("UP", "BULL", "TRENDING_UP")
    )
    if against:
        ctx_note = f"Index {idx} AGAINST trade direction"
        ctx_score = 25.0
    elif aligned:
        ctx_note = f"Index {idx} aligned; sector {sec or 'n/a'}"
        ctx_score = 85.0
    else:
        ctx_note = f"Index/sector neutral ({idx or 'flat'}) — not a veto"
        ctx_score = 68.0

    # 4) S/R inside target zone — advisory only
    sr_note = "No major swing level flagged in target path"
    sr_score = 70.0
    if target:
        swing_hi = float(df["high"].max())
        swing_lo = float(df["low"].min())
        if is_long and swing_hi >= target * 0.995:
            sr_note = f"Prior swing high {swing_hi:.2f} near target — target may be tight"
            sr_score = 40.0
        elif not is_long and swing_lo <= target * 1.005:
            sr_note = f"Prior swing low {swing_lo:.2f} near target — target may be tight"
            sr_score = 48.0

    # 5) ATR vs stop — wide tolerance
    stop_dist = abs(entry - stop)
    atr_ok = atr_val <= 0 or 0.35 * atr_val <= stop_dist <= 3.0 * atr_val
    atr_note = (
        f"Stop {stop_dist:.2f} vs ATR {atr_val:.2f} — {'reasonable' if atr_ok else 'mis-sized'}"
    )
    atr_score = 75.0 if atr_ok else 30.0

    scores = [pa_score, vol_score, ctx_score, sr_score, atr_score]
    avg = sum(scores) / len(scores)
    confidence = _confidence_label(avg)

    if against and avg < 45:
        action = "Skip"
    elif avg >= 58 and not against:
        action = "Take the trade as-is"
    elif avg >= 42 and not against:
        action = "Take with adjusted stop-loss or target"
    else:
        action = "Skip"

    factor_notes = [pa_note, vol_note, ctx_note, sr_note, atr_note]

    prompt = format_entry_confirmation_prompt(
        strategy=strategy,
        side=side,
        entry=round(entry, 2),
        stop=round(stop, 2),
        target=round(target, 2) if target else "—",
        candle_count=len(df),
        timeframe=timeframe,
        rsi=round(rsi_val, 1),
        atr=round(atr_val, 2),
        indicator_context=f"VWAP={vwap_val:.2f}, spot={spot:.2f}",
        index_context=f"{index_trend or 'flat'} / sector {sector_trend or 'n/a'}",
    )

    return {
        "confidence": confidence,
        "confidence_score": round(avg, 1),
        "action": action,
        "factor_notes": factor_notes,
        "prompt": prompt,
        "scores": {
            "price_action": pa_score,
            "volume": vol_score,
            "index_alignment": ctx_score,
            "support_resistance": sr_score,
            "atr_stop": atr_score,
        },
    }


def _vwap_reclaimed(df: pd.DataFrame, vwap: float, is_long: bool, bars: int = 2) -> bool:
    """Require consecutive closes on the wrong side of VWAP — not a single dip."""
    if df.empty or len(df) < bars or vwap is None:
        return False
    tail = df.tail(bars)
    if is_long:
        return all(float(row["close"]) < vwap for _, row in tail.iterrows())
    return all(float(row["close"]) > vwap for _, row in tail.iterrows())


def evaluate_dynamic_exit(
    *,
    engine: str,
    side: str,
    entry: float,
    stop: float,
    target: float | None,
    strategy: str,
    current: float,
    candles: pd.DataFrame,
    entry_time: Any = None,
    bar_time: Any = None,
    bars_held: int = 0,
    max_hold_bars: int | None = None,
    max_hold_days: int | None = None,
    vwap: float | None = None,
    atr_at_entry: float | None = None,
) -> dict[str, Any]:
    """
    Dynamic exit reasoning (prompt #2) with intraday/swing add-ons (#3/#4).
    """
    is_long = _side_is_long(side)
    df = candles.copy() if candles is not None and not candles.empty else pd.DataFrame()
    move = (current - entry) if is_long else (entry - current)
    risk = abs(entry - stop) if stop else 0.0
    target_pts = abs((target or entry) - entry) if target else risk * 2
    pnl_r = move / risk if risk > 0 else 0.0

    momentum_label, momentum_score = _recent_momentum(df, is_long)
    steps: list[str] = [f"Momentum: {momentum_label}"]

    assessment = "Hold"
    revised_stop = stop
    revised_target = target
    confidence_score = 60.0

    # Target proximity — tighten only when very close and fading; never force exit here
    if target and target_pts > 0:
        progress = move / target_pts if target_pts else 0
        if progress >= 0.88 and momentum_score < 48:
            assessment = "Tighten stop to lock gains"
            lock = entry + move * 0.72 if is_long else entry - move * 0.72
            revised_stop = max(revised_stop, lock) if is_long else min(revised_stop, lock)
            steps.append("Near target with fading momentum — tighten, hold for target")
            confidence_score = 75.0

    # Thesis invalidation — VWAP reclaim only when meaningfully underwater
    if vwap is not None and not df.empty and _vwap_reclaimed(df, vwap, is_long):
        if pnl_r <= -0.2 or (pnl_r <= -0.05 and momentum_score <= 22):
            assessment = "Exit fully now"
            steps.append("Invalidation: sustained VWAP reclaim against position while weak")
            confidence_score = 86.0

    # Volatility shift — tighten only when in profit
    atr_now = _atr14(df)
    if atr_at_entry and atr_at_entry > 0 and pnl_r > 0.25:
        ratio = atr_now / atr_at_entry
        if ratio > 1.5 and assessment == "Hold":
            assessment = "Tighten stop to lock gains"
            steps.append(f"Volatility expanded {ratio:.1f}x — tighten while in profit")
            confidence_score = max(confidence_score, 70.0)

    # Engine-specific add-ons
    now = datetime.now(IST)
    if bar_time is not None:
        try:
            now = pd.to_datetime(bar_time)
            if now.tzinfo is None:
                now = now.tz_localize(IST)
            else:
                now = now.tz_convert(IST)
        except (ValueError, TypeError):
            pass
    elif entry_time:
        try:
            now = pd.to_datetime(entry_time).tz_convert(IST) if hasattr(entry_time, "tzinfo") else now
        except (ValueError, TypeError):
            pass

    if engine == "intraday":
        minutes = now.hour * 60 + now.minute
        if minutes >= 15 * 60 + 15:
            assessment = "Exit fully now"
            steps.append("Intraday hard rule: 3:15 PM — flat all intraday positions")
            confidence_score = 99.0
        elif minutes <= 9 * 60 + 30 or minutes >= 15 * 60 + 15:
            confidence_score = min(confidence_score, 55.0)
            steps.append("Erratic open/close window — lower confidence")
        if len(df) >= 4 and "volume" in df.columns and pnl_r <= -0.15:
            vol_tail = float(df["volume"].tail(3).mean())
            vol_day = float(df["volume"].mean()) or vol_tail
            if vol_tail < vol_day * 0.65 and momentum_score < 42:
                assessment = "Exit fully now"
                steps.append("Volume exhaustion while trade not working")
                confidence_score = max(confidence_score, 78.0)

    if engine == "swing":
        if risk > 0 and pnl_r >= 1.0 and assessment == "Hold":
            revised_stop = entry
            assessment = "Tighten stop to breakeven"
            steps.append("Swing +1R rule — stop to breakeven")
            confidence_score = 80.0
        if max_hold_days and bars_held >= int(max_hold_days * 1.15) and abs(pnl_r) < 0.15:
            assessment = "Exit fully now"
            steps.append(f"Time decay: {bars_held}d held with no progress")
            confidence_score = 70.0
        if len(df) >= 5 and pnl_r <= 0:
            highs = df["high"].astype(float).tail(5)
            if is_long and highs.iloc[-1] < highs.iloc[-2] < highs.iloc[-3]:
                assessment = "Exit fully now"
                steps.append("Swing structure: lower highs while underwater")
                confidence_score = max(confidence_score, 76.0)

    if momentum_score <= 18 and pnl_r <= 0 and assessment == "Hold":
        assessment = "Exit fully now"
        steps.append("Momentum reversed while trade underwater")
        confidence_score = 82.0

    exit_now = assessment == "Exit fully now"
    hard_exit = exit_now and confidence_score >= 95.0
    # AI exits cut losses; strategy targets/trailing handle winners (improves win rate).
    if exit_now and not hard_exit and pnl_r > 0:
        assessment = "Hold"
        exit_now = False
        steps.append("In profit — defer to strategy target/stop")
    reasoning = " ".join(steps)
    prompt = format_dynamic_exit_prompt(
        entry=round(entry, 2),
        stop=round(stop, 2),
        target=round(target, 2) if target else "—",
        strategy=strategy,
        held=f"{bars_held} bars",
        current=round(current, 2),
        pnl=round(move, 2),
    )
    return {
        "assessment": assessment,
        "reasoning": reasoning,
        "revised_stop": round(revised_stop, 2) if revised_stop else None,
        "revised_target": round(revised_target, 2) if revised_target else None,
        "confidence": _confidence_label(confidence_score),
        "confidence_score": round(confidence_score, 1),
        "should_exit": exit_now and confidence_score >= 78.0,
        "should_tighten": "Tighten" in assessment,
        "prompt": prompt,
        "steps": steps,
    }


def review_closed_trade(
    *,
    trade: dict[str, Any],
    candles_after: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Post-trade review (prompt #5) — factual timing vs continuation after exit."""
    entry = float(trade.get("entry") or trade.get("entry_price") or 0)
    exit_px = float(trade.get("exit") or 0)
    orig_target = trade.get("target")
    orig_stop = trade.get("stoploss") or trade.get("stop")
    side = trade.get("side") or trade.get("signal_type") or "BUY"
    is_long = _side_is_long(str(side))

    timing = "well-timed"
    continuation = "unknown"
    if candles_after is not None and not candles_after.empty and exit_px > 0:
        post = candles_after.head(10)
        if is_long:
            best = float(post["high"].max())
            worst = float(post["low"].min())
            if best > exit_px * 1.003:
                continuation = "continued higher"
                timing = "early"
            elif worst < exit_px * 0.997:
                continuation = "reversed lower"
                timing = "well-timed" if float(trade.get("pnl") or 0) >= 0 else "late"
            else:
                continuation = "sideways"
                timing = "well-timed"
        else:
            best = float(post["low"].min())
            worst = float(post["high"].max())
            if best < exit_px * 0.997:
                continuation = "continued lower"
                timing = "early"
            elif worst > exit_px * 1.003:
                continuation = "reversed higher"
                timing = "well-timed" if float(trade.get("pnl") or 0) >= 0 else "late"
            else:
                continuation = "sideways"
                timing = "well-timed"

    target_realistic = True
    if orig_target and entry:
        target_realistic = abs(float(orig_target) - entry) <= abs(entry - float(orig_stop or entry)) * 3

    improvement = "Weight momentum fade more heavily near target"
    if timing == "early":
        improvement = "Allow partial profit instead of full exit when within 20% of target"
    elif timing == "late":
        improvement = "Exit on thesis invalidation (VWAP/structure) before hard stop"

    prompt = POST_TRADE_REVIEW_PROMPT

    return {
        "exit_timing": timing,
        "post_exit_continuation": continuation,
        "target_was_realistic": target_realistic,
        "improvement_factor": improvement,
        "prompt": prompt,
        "summary": (
            f"Exit was {timing} relative to next 10 bars ({continuation}). "
            f"Target {'looked realistic' if target_realistic else 'may have been ambitious'}."
        ),
    }
