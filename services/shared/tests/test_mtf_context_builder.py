import pandas as pd

from trading_shared.strategies.scalping_desk.mtf_context_builder import (
    build_mtf_analysis,
    merge_mtf_into_context,
    mtf_blocks_signal,
    prepare_mtf_frames,
)


def _make_uptrend_1m(n: int = 180, start: float = 100.0) -> pd.DataFrame:
    rows = []
    for i in range(n):
        px = start + i * 0.15
        rows.append(
            {
                "timestamp": f"2025-06-02T09:{i // 60 + 15:02d}:{i % 60:02d}",
                "open": px,
                "high": px + 0.2,
                "low": px - 0.05,
                "close": px + 0.1,
                "volume": 1000 + i,
            }
        )
    return pd.DataFrame(rows)


def _make_downtrend_1m(n: int = 180, start: float = 120.0) -> pd.DataFrame:
    rows = []
    for i in range(n):
        px = start - i * 0.12
        rows.append(
            {
                "timestamp": f"2025-06-02T09:{i // 60 + 15:02d}:{i % 60:02d}",
                "open": px,
                "high": px + 0.05,
                "low": px - 0.2,
                "close": px - 0.1,
                "volume": 1000 + i,
            }
        )
    return pd.DataFrame(rows)


def test_prepare_mtf_frames():
    df = _make_uptrend_1m()
    df_5m, df_15m, df_1h = prepare_mtf_frames(df)
    assert len(df_5m) > 0
    assert len(df_15m) > 0
    assert len(df_1h) > 0


def test_uptrend_bias_positive():
    df = _make_uptrend_1m()
    out = build_mtf_analysis(df)
    assert out["trend_1h"] == "up"
    assert out["bias_score"] > 0
    assert "support" in out["sr_levels"]
    assert "resistance" in out["sr_levels"]
    assert len(out["reasoning"].split()) <= 30 or len(out["reasoning"]) <= 120


def test_downtrend_bias_negative():
    df = _make_downtrend_1m()
    out = build_mtf_analysis(df)
    assert out["trend_1h"] == "down"
    assert out["bias_score"] < 0


def test_merge_mtf_into_context():
    mtf = build_mtf_analysis(_make_uptrend_1m())
    ctx = merge_mtf_into_context({"spot": 110}, mtf)
    assert ctx["mtf"]["bias_score"] == mtf["bias_score"]
    assert ctx["direction"] in ("up", "down", "neutral")


def test_mtf_blocks_counter_put_in_uptrend():
    mtf = {"trend_1h": "up", "alignment_15m": "counter", "bias_score": -6}
    assert mtf_blocks_signal(mtf, "PUT") is True
    assert mtf_blocks_signal(mtf, "CALL") is False
