"""Tests for adaptive scalping session gate."""

from __future__ import annotations

import pandas as pd

from trading_shared.strategies.scalping_desk.adaptive_session import (
    evaluate_adaptive_session,
    in_market_hours,
    mtf_aligns_with_signal,
)
from trading_shared.strategies.scalping_desk.engine import enrich_candles


def _trending_df(n: int = 60, *, base: float = 24000.0, step: float = 3.0) -> pd.DataFrame:
    rows = []
    for i in range(n):
        close = base + i * step
        rows.append(
            {
                "timestamp": f"2026-07-09T10:{i % 60:02d}:00+05:30",
                "open": close - 1,
                "high": close + 4,
                "low": close - 4,
                "close": close,
                "volume": 1000 + i * 50,
            }
        )
    return pd.DataFrame(rows)


def test_in_market_hours_rejects_weekend():
    assert in_market_hours("2026-07-11T10:00:00+05:30") is False


def test_adaptive_session_passes_strong_trend():
    df = enrich_candles(_trending_df())
    result = evaluate_adaptive_session(
        df,
        instrument_key="nifty50",
        mtf_context={"trend_15m": "up", "alignment_15m": "aligned"},
        ts="2026-07-09T10:30:00+05:30",
    )
    assert result["session_ok"] is True
    assert "atr" in result["checks"]
    assert result["checks"]["volume"]["ok"] is True


def test_adaptive_session_blocks_low_adx_chop():
    flat = pd.DataFrame(
        {
            "timestamp": [f"2026-07-09T10:{i:02d}:00+05:30" for i in range(40)],
            "open": [24000.0] * 40,
            "high": [24002.0] * 40,
            "low": [23998.0] * 40,
            "close": [24000.0] * 40,
            "volume": [500.0] * 40,
        }
    )
    df = enrich_candles(flat)
    result = evaluate_adaptive_session(
        df,
        instrument_key="nifty50",
        mtf_context={"trend_15m": "sideways", "alignment_15m": "neutral"},
        ts="2026-07-09T10:30:00+05:30",
    )
    assert result["session_ok"] is False
    assert "adx" in result["failed"] or "mtf_align" in result["failed"]


def test_mtf_aligns_with_signal_direction():
    mtf = {"trend_15m": "up", "alignment_15m": "aligned"}
    assert mtf_aligns_with_signal(mtf, "CALL") is True
    assert mtf_aligns_with_signal(mtf, "PUT") is False


def test_vwap_allowed_when_15m_sideways():
    mtf = {"trend_15m": "sideways", "alignment_15m": "neutral"}
    assert mtf_aligns_with_signal(mtf, "CALL", strategy_id="vwap_bounce") is True
    assert mtf_aligns_with_signal(mtf, "PUT", strategy_id="ema_crossover_rsi") is True
    assert mtf_aligns_with_signal(mtf, "CALL", strategy_id="momentum_burst") is False


def test_smc_orb_allowed_when_15m_sideways():
    mtf = {"trend_15m": "sideways", "alignment_15m": "neutral"}
    assert mtf_aligns_with_signal(mtf, "PUT", strategy_id="smc_orb_fvg") is True
    assert mtf_aligns_with_signal(mtf, "CALL", strategy_id="smc_orb_fvg") is True


def test_spread_check_skipped_without_live_quote():
    df = enrich_candles(_trending_df())
    row = df.iloc[-1]
    from trading_shared.strategies.scalping_desk.adaptive_session import _check_spread

    result = _check_spread(row, tick=None, instrument_key="nifty50")
    assert result["ok"] is True
    assert "skipped" in result["detail"].lower()


def test_adaptive_session_blocks_upcoming_news():
    df = enrich_candles(_trending_df())
    macro = {
        "economic_events": [
            {"title": "RBI Policy", "impact": "high", "at": "2026-07-09T10:35:00+05:30"},
        ]
    }
    result = evaluate_adaptive_session(
        df,
        instrument_key="nifty50",
        mtf_context={"trend_15m": "up", "alignment_15m": "aligned"},
        macro_inputs=macro,
        ts="2026-07-09T10:30:00+05:30",
    )
    assert result["session_ok"] is False
    assert "news_clear" in result["failed"]
