from trading_shared.strategies.scalping_desk.orb_breakout_confirmation import (
    confirm_orb_breakout,
    confirm_orb_from_df,
    orb_confirmation_allows_entry,
)


def test_nifty_or_tradeable_range():
    out = confirm_orb_breakout(
        instrument_key="nifty50",
        or_high=25100,
        or_low=25040,
        current_price=25105,
        close=25105,
        vol_ratio=1.6,
        gap_percent=0.2,
        timestamp="2025-06-02T10:05:00+05:30",
        bar_open=25098,
    )
    assert out["or_tradeable"] is True
    assert out["or_range"] == 60
    assert out["breakout_direction"] == "up"
    assert out["entry"] > 0
    assert out["target"] > out["entry"] > out["sl"]


def test_banknifty_ideal_range():
    out = confirm_orb_breakout(
        instrument_key="banknifty",
        or_high=51200,
        or_low=51050,
        current_price=51040,
        close=51040,
        vol_ratio=1.55,
        gap_percent=-0.1,
        timestamp="2025-06-02T09:45:00+05:30",
        bar_open=51055,
    )
    assert out["or_tradeable"] is True
    assert out["breakout_direction"] == "down"


def test_narrow_range_not_tradeable():
    out = confirm_orb_breakout(
        instrument_key="nifty50",
        or_high=25020,
        or_low=25000,
        current_price=25025,
        close=25025,
        vol_ratio=1.6,
    )
    assert out["or_tradeable"] is False


def test_high_fake_risk_on_gap_fill():
    out = confirm_orb_breakout(
        instrument_key="nifty50",
        or_high=25100,
        or_low=25040,
        current_price=25070,
        close=25070,
        vol_ratio=1.2,
        gap_percent=1.5,
        prev_close=24950,
        timestamp="2025-06-02T10:10:00+05:30",
        macro={"regime": "EVENT_DRIVEN"},
    )
    assert out["fake_risk"] in ("medium", "high")


def test_orb_allows_entry():
    ok = {
        "or_tradeable": True,
        "breakout_direction": "up",
        "fake_risk": "low",
        "confidence": "high",
    }
    assert orb_confirmation_allows_entry(ok, "CALL") is True
    assert orb_confirmation_allows_entry(ok, "PUT") is False


def test_confirm_orb_from_df():
    import pandas as pd

    rows = []
    base = 25000.0
    for i in range(30):
        px = base + (i % 5)
        rows.append(
            {
                "timestamp": f"2025-06-02T09:{20 + i // 60:02d}:{i % 60:02d}",
                "open": px,
                "high": px + 8,
                "low": px - 2,
                "close": px + 5,
                "volume": 2000 + i * 50,
            }
        )
    for i in range(10):
        px = base + 65 + i
        rows.append(
            {
                "timestamp": f"2025-06-02T10:{i:02d}:00",
                "open": px,
                "high": px + 3,
                "low": px - 1,
                "close": px + 2,
                "volume": 5000,
            }
        )
    df = pd.DataFrame(rows)
    out = confirm_orb_from_df("nifty50", df, spot=base + 75)
    assert out is not None
    assert "or_high" in out
