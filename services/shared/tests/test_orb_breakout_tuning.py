"""ORB breakout tuning helpers."""

from trading_shared.strategies.scalping_desk.orb_breakout_tuning import (
    ORB_BREAKOUT_BANK_DEFAULTS,
    ORB_BREAKOUT_BANK_LEGACY,
    merge_orb_params,
    orb_candidate_grid,
    score_orb_backtest,
)


def test_merge_orb_params_nested():
    merged = merge_orb_params({"orb_breakout": {"orb_vol_min": 1.2, "orb_stop_pts": 52.0}})
    assert merged["orb_vol_min"] == 1.2
    assert merged["orb_stop_pts"] == 52.0
    assert merged["orb_or_range_min"] == ORB_BREAKOUT_BANK_DEFAULTS["orb_or_range_min"]


def test_candidate_grid_includes_legacy_and_tuned():
    grid = orb_candidate_grid()
    assert ORB_BREAKOUT_BANK_LEGACY in grid or any(
        g.get("orb_vol_min") == 1.35 for g in grid
    )
    assert len(grid) >= 10


def test_score_penalizes_few_trades():
    low = score_orb_backtest({"total_trades": 2, "win_rate": 80, "profit_factor": 2, "total_pnl": 1000})
    ok = score_orb_backtest({"total_trades": 12, "win_rate": 55, "profit_factor": 1.4, "total_pnl": 2000})
    assert ok > low
