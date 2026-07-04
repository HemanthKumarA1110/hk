"""Rank Nifty 50 swing candidates using screen + walk-forward backtest preview."""

from __future__ import annotations

import pandas as pd

from trading_shared.market.scrip_master import NIFTY50_SYMBOLS
from trading_shared.strategies.swing_desk.session import WARMUP_BARS, enrich_swing_frame
from trading_shared.strategies.swing_desk.strategies import get_strategy


def default_universe() -> list[str]:
    return list(NIFTY50_SYMBOLS)


def score_swing_candidate(df: pd.DataFrame, strategy_code: str) -> float:
    """Quantitative screen: trend strength, volatility, volume, signal density."""
    if df is None or len(df) < WARMUP_BARS:
        return 0.0

    enriched = enrich_swing_frame(df)
    if enriched.empty:
        return 0.0

    close = enriched["close"]
    ema200 = enriched["ema200"]
    trend = 0.0
    if float(ema200.iloc[-1]) > 0:
        trend = min(max((float(close.iloc[-1]) / float(ema200.iloc[-1]) - 1) * 100, 0), 15)

    vol_tail = float(enriched["volume"].tail(20).mean())
    vol_base = float(enriched["volume"].mean()) or 1.0
    rel_vol = min(vol_tail / vol_base, 3.0)

    returns = close.pct_change().dropna()
    momentum = min(abs(float(returns.tail(min(20, len(returns))).sum())) * 100, 12.0)

    signal_density = _signal_density(enriched, strategy_code)

    return round(trend * 4 + rel_vol * 18 + momentum * 6 + signal_density * 48, 2)


def _signal_density(df: pd.DataFrame, strategy_code: str) -> float:
    try:
        strategy = get_strategy(strategy_code=strategy_code)
    except ValueError:
        return 0.0

    hits = 0
    start = max(WARMUP_BARS, len(df) - 80)
    for idx in range(start, len(df)):
        if strategy.try_entry(df, idx, in_position=False):
            hits += 1
    return min(hits / 2.0, 10.0)


def rank_universe(
    symbol_frames: list[tuple[str, pd.DataFrame]],
    strategy_code: str,
    *,
    use_backtest_score: bool = True,
) -> list[dict]:
    from trading_shared.strategies.swing_desk.backtest import run_swing_portfolio_backtest

    ranked: list[dict] = []
    for symbol, df in symbol_frames:
        screen = score_swing_candidate(df, strategy_code)
        if screen <= 0:
            continue

        score = screen
        win_rate = None
        profit_factor = None
        preview_pnl = None

        if use_backtest_score and len(df) >= WARMUP_BARS:
            try:
                preview = run_swing_portfolio_backtest(
                    {symbol: df},
                    strategy_code,
                    initial_capital=50_000,
                    risk_pct=1.0,
                    max_open_positions=1,
                )
                win_rate = preview["win_rate"]
                profit_factor = preview["profit_factor"]
                preview_pnl = preview["total_pnl"]
                trades = preview["total_trades"]
                if trades < 1:
                    continue
                if preview_pnl < 0:
                    continue
                if trades >= 2 and win_rate < 45:
                    continue
                if trades >= 2:
                    score = round(
                        win_rate * 0.5
                        + min(profit_factor, 4.0) * 14
                        + preview_pnl / 500
                        - preview["max_drawdown"] * 0.3
                        + screen * 0.12,
                        2,
                    )
                else:
                    score = round(win_rate * 0.45 + screen * 0.2, 2)
            except Exception:
                score = screen

        ranked.append(
            {
                "symbol": symbol,
                "score": score,
                "screen_score": round(screen, 2),
                "preview_win_rate": win_rate,
                "preview_profit_factor": profit_factor,
                "preview_pnl": preview_pnl,
            }
        )

    ranked.sort(key=lambda row: row["score"], reverse=True)

    if not ranked and use_backtest_score:
        for symbol, df in symbol_frames:
            screen = score_swing_candidate(df, strategy_code)
            if screen <= 0:
                continue
            ranked.append({"symbol": symbol, "score": screen, "screen_score": round(screen, 2)})
        ranked.sort(key=lambda row: row["score"], reverse=True)

    return ranked
