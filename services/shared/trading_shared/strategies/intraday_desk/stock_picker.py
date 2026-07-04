"""Rank Nifty 50 candidates for intraday backtesting from historical OHLCV."""

from __future__ import annotations

import pandas as pd

from trading_shared.market.scrip_master import NIFTY50_SYMBOLS
from trading_shared.strategies.intraday_desk.session import enrich_intraday_frame, trading_date
from trading_shared.strategies.intraday_desk.strategies import get_strategy

WARMUP = 25
DEFAULT_UNIVERSE = list(NIFTY50_SYMBOLS)


def default_universe() -> list[str]:
    return list(DEFAULT_UNIVERSE)


def score_intraday_candidate(df: pd.DataFrame, strategy_code: str) -> float:
    """Quantitative screen: volume, range, momentum, and strategy signal density."""
    if df is None or len(df) < WARMUP + 5:
        return 0.0

    enriched = enrich_intraday_frame(df)
    if enriched.empty:
        return 0.0

    vol_tail = float(enriched["volume"].tail(20).mean())
    vol_base = float(enriched["volume"].mean()) or 1.0
    rel_vol = min(vol_tail / vol_base, 3.0)

    range_pct = float(((enriched["high"] - enriched["low"]) / enriched["close"].replace(0, 1)).mean() * 100)
    range_pct = min(range_pct, 3.0)

    returns = enriched["close"].pct_change().dropna()
    momentum = min(abs(float(returns.tail(min(50, len(returns))).sum())) * 100, 8.0)

    signal_density = _signal_density(enriched, strategy_code)

    return round(rel_vol * 22 + range_pct * 18 + momentum * 8 + signal_density * 52, 2)


def _signal_density(df: pd.DataFrame, strategy_code: str) -> float:
    """Estimate how often the strategy would have triggered (0–10 scale)."""
    try:
        strategy = get_strategy(strategy_code=strategy_code)
    except ValueError:
        return 0.0

    hits = 0
    samples = 0
    traded_days: set = set()
    step = max(len(df) // 40, 1)

    for i in range(WARMUP, len(df), step):
        row = df.iloc[i]
        day = trading_date(row["timestamp"])
        traded_today = day in traded_days
        if strategy.try_entry(df, i, traded_today):
            hits += 1
            traded_days.add(day)
        samples += 1

    if samples == 0:
        return 0.0
    rate = hits / samples
    return min(rate * 40, 10.0)


def rank_universe(
    symbol_frames: list[tuple[str, pd.DataFrame]],
    strategy_code: str,
    *,
    use_backtest_score: bool = True,
) -> list[dict]:
    """Return scored symbols sorted best-first (screen + optional walk-forward backtest)."""
    from trading_shared.strategies.intraday_desk.backtest import run_intraday_strategy_backtest

    ranked: list[dict] = []
    for symbol, df in symbol_frames:
        screen = score_intraday_candidate(df, strategy_code)
        if screen <= 0:
            continue

        score = screen
        win_rate = None
        profit_factor = None
        preview_pnl = None

        if use_backtest_score and len(df) >= WARMUP + 5:
            try:
                preview = run_intraday_strategy_backtest(
                    df,
                    strategy_code,
                    symbol,
                    initial_capital=50_000,
                    risk_pct=1.0,
                )
                win_rate = preview["win_rate"]
                profit_factor = preview["profit_factor"]
                preview_pnl = preview["total_pnl"]
                trades = preview["total_trades"]
                if trades < 1:
                    continue
                if trades >= 2:
                    score = round(
                        win_rate * 0.55
                        + min(profit_factor, 4.0) * 12
                        + preview_pnl / 400
                        - preview["max_drawdown"] * 0.35
                        + screen * 0.15,
                        2,
                    )
                else:
                    score = round(win_rate * 0.4 + screen * 0.25, 2)
                if preview_pnl < 0 and win_rate < 40:
                    continue
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
            screen = score_intraday_candidate(df, strategy_code)
            if screen <= 0:
                continue
            ranked.append({"symbol": symbol, "score": screen, "screen_score": round(screen, 2)})

        ranked.sort(key=lambda row: row["score"], reverse=True)

    return ranked
