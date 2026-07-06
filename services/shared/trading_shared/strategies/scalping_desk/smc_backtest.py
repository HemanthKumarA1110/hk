"""
SMC strategy backtest — 30-day comparison, ranking, and parameter optimization.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any

import pandas as pd

from trading_shared.strategies.scalping_desk.engine import (
    enrich_candles,
    estimate_option_mark_premium,
    max_hold_bars,
    should_exit,
    should_exit_index,
)
from trading_shared.strategies.scalping_desk.smc_scalping_engine import (
    DEFAULT_SMC_PARAMS,
    SMC_EVALUATORS,
    SMC_REGISTRY,
    SMC_STRATEGY_IDS,
    mtf_context_at,
    prepare_mtf_frames,
)
from trading_shared.strategies.scalping_desk.capital_utilization import (
    backtest_option_trade_pnl,
    backtest_size_for_bar,
)
from trading_shared.strategies.scalping_desk.option_execution import OPTION_EXECUTION_BUY_ONLY

SMC_MAX_BARS = 7500  # ~20 trading days — balances coverage vs runtime
BACKTEST_LOOKBACK = 90
MIN_BARS_BETWEEN_TRADES = 8
ENTRY_SCAN_EVERY = 3


@dataclass
class SMCTrade:
    entry_time: str
    exit_time: str
    signal_type: str
    entry: float
    exit: float
    pnl: float
    result: str
    duration_bars: int
    exit_reason: str
    strategy_id: str
    risk_reward: float = 0


def _trade_day(ts: str) -> str:
    return ts[:10] if len(ts) >= 10 else "unknown"


def _run_single_strategy(
    candles: pd.DataFrame,
    strategy_id: str,
    lot_size: int,
    capital: float,
    *,
    instrument_key: str = "nifty50",
    params: dict[str, Any] | None = None,
    max_loss_per_day: float = 5000,
    max_trades_per_day: int = 8,
    capital_utilization_pct: float = 0.95,
    max_lots_per_trade: int = 0,
    option_execution_mode: str = OPTION_EXECUTION_BUY_ONLY,
) -> dict[str, Any]:
    """Replay one SMC strategy on historical 1m candles."""
    if candles.empty or len(candles) < 60:
        return _empty(strategy_id, "Insufficient candles", capital=capital)

    frame = candles.reset_index(drop=True)
    max_bars = int((params or {}).get("smc_max_bars", SMC_MAX_BARS))
    if instrument_key == "banknifty" and strategy_id == "smc_fvg_ob_bos":
        from trading_shared.strategies.scalping_desk.smc_fvg_ob_bos_tuning import merge_smc_fvg_ob_bos_params

        max_bars = int(merge_smc_fvg_ob_bos_params(params).get("smc_max_bars", SMC_MAX_BARS))
    elif instrument_key == "banknifty" and strategy_id == "smc_orb_fvg":
        from trading_shared.strategies.scalping_desk.smc_orb_fvg_tuning import merge_smc_orb_fvg_params

        max_bars = int(merge_smc_orb_fvg_params(params).get("smc_max_bars", SMC_MAX_BARS))
    if len(frame) > max_bars:
        frame = frame.tail(max_bars).reset_index(drop=True)

    data = enrich_candles(frame)
    pre = prepare_mtf_frames(data)
    if instrument_key == "banknifty" and strategy_id == "smc_fvg_ob_bos":
        from trading_shared.strategies.scalping_desk.smc_fvg_ob_bos_tuning import merge_smc_fvg_ob_bos_params

        merged = merge_smc_fvg_ob_bos_params(params)
    elif instrument_key == "banknifty" and strategy_id == "smc_orb_fvg":
        from trading_shared.strategies.scalping_desk.smc_orb_fvg_tuning import merge_smc_orb_fvg_params

        merged = merge_smc_orb_fvg_params(params)
    else:
        merged = {**DEFAULT_SMC_PARAMS, **(params or {})}
    evaluator = SMC_EVALUATORS.get(strategy_id)
    if not evaluator:
        return _empty(strategy_id, f"Unknown strategy {strategy_id}", capital=capital)

    entry_scan = int(merged.get("smc_entry_scan_every", ENTRY_SCAN_EVERY))
    min_between = int(merged.get("smc_min_bars_between", MIN_BARS_BETWEEN_TRADES))
    trades: list[SMCTrade] = []
    equity = capital
    equity_curve = [{"index": 0, "equity": equity, "date": str(data.iloc[0].get("timestamp", 0))}]
    active = None
    last_exit = -min_between
    day_pnl: dict[str, float] = {}
    day_trades: dict[str, int] = {}
    hold_limit = int(merged.get("max_hold_bars", max_hold_bars(instrument_key)))
    trailing_mult = float(merged.get("trailing_atr_mult", 0.75))
    max_lots = int(max_lots_per_trade or 0)
    bankrupt = False

    for i in range(BACKTEST_LOOKBACK, len(data)):
        row = data.iloc[i]
        ts = str(row.get("timestamp", i))
        spot = float(row["close"])
        day = _trade_day(ts)
        atr = float(row.get("atr") or spot * 0.002)

        if active:
            bars_held = i - active["entry_index"]
            trail_floor = None
            if trailing_mult > 0:
                if active["signal_type"] == "CALL":
                    peak = float(active.get("peak_spot", spot))
                    if spot > peak:
                        active["peak_spot"] = spot
                        peak = spot
                    peak_move = peak - active["entry_spot"]
                    if peak_move > 0:
                        trail_floor = peak_move * trailing_mult
                else:
                    trough = float(active.get("trough_spot", spot))
                    if spot < trough:
                        active["trough_spot"] = spot
                        trough = spot
                    peak_move = active["entry_spot"] - trough
                    if peak_move > 0:
                        trail_floor = peak_move * trailing_mult

            entry_premium = float(active.get("entry") or 0)
            entry_spot = float(active.get("entry_spot") or spot)
            current_premium = estimate_option_mark_premium(
                entry_premium, active["signal_type"], entry_spot, spot
            )
            exit_hit, reason = should_exit(
                active["signal_type"],
                current_premium,
                entry_premium,
                float(active.get("target") or entry_premium * 1.08),
                float(active.get("stoploss") or entry_premium * 0.88),
                active.get("indicators") or {},
            )
            if not exit_hit:
                exit_hit, reason = should_exit_index(
                    active["signal_type"],
                    spot,
                    entry_spot,
                    active["target_pts"],
                    active["stop_pts"],
                    bars_held=bars_held,
                    max_hold=active.get("max_hold_bars") or hold_limit,
                    trail_floor_move=trail_floor,
                )
            if exit_hit or reason:
                trade_lots = int(active.get("lots") or 1)
                pnl = backtest_option_trade_pnl(
                    entry_premium,
                    current_premium,
                    lot_size,
                    trade_lots,
                )
                equity += pnl
                equity = max(0.0, equity)
                if equity <= 0:
                    bankrupt = True
                day_pnl[day] = day_pnl.get(day, 0.0) + pnl
                day_trades[day] = day_trades.get(day, 0) + 1
                rr = active["target_pts"] / max(active["stop_pts"], 0.01)
                trades.append(
                    SMCTrade(
                        entry_time=active["entry_time"],
                        exit_time=ts,
                        signal_type=active["signal_type"],
                        entry=active["entry_spot"],
                        exit=round(spot, 2),
                        pnl=round(pnl, 2),
                        result="Win" if pnl > 0 else "Loss",
                        duration_bars=bars_held,
                        exit_reason=reason or "unknown",
                        strategy_id=strategy_id,
                        risk_reward=round(rr, 2),
                    )
                )
                active = None
                last_exit = i

        daily_pnl = day_pnl.get(day, 0.0)
        if (
            active is None
            and not bankrupt
            and equity > 0
            and (i - BACKTEST_LOOKBACK) % entry_scan == 0
            and i - last_exit >= min_between
            and daily_pnl > -abs(max_loss_per_day)
            and day_trades.get(day, 0) < max_trades_per_day
        ):
            mtf = mtf_context_at(pre, i, BACKTEST_LOOKBACK)
            setup = evaluator(mtf, merged)
            if setup:
                stop_pts = setup.stop_pts or atr * float(merged["stop_atr_mult"])
                target_pts = setup.target_pts or atr * float(merged["target_atr_mult"])
                lots, _, premium = backtest_size_for_bar(
                    initial_capital=capital,
                    instrument_key=instrument_key,
                    spot=spot,
                    day=day,
                    day_pnl=day_pnl,
                    utilization_pct=capital_utilization_pct,
                    max_lots=max_lots,
                    current_equity=equity,
                )
                if lots < 1:
                    continue
                active = {
                    "signal_type": setup.signal_type,
                    "entry_time": ts,
                    "entry_index": i,
                    "entry_spot": spot,
                    "lots": lots,
                    "capital_deployed": round(lots * premium * lot_size, 2),
                    "stop_pts": stop_pts,
                    "target_pts": target_pts,
                    "max_hold_bars": hold_limit,
                    "peak_spot": spot,
                    "trough_spot": spot,
                    "trail_stop_pts": 0,
                }

        if i % 20 == 0 or i == len(data) - 1:
            equity_curve.append({"index": i, "equity": round(equity, 2), "date": ts})

    return _summarize(trades, equity_curve, capital, strategy_id, len(data), merged)


def run_single_smc_backtest(
    candles: pd.DataFrame,
    strategy_id: str,
    lot_size: int,
    capital: float,
    *,
    instrument_key: str = "nifty50",
    params: dict[str, Any] | None = None,
    max_loss_per_day: float = 5000,
    max_trades_per_day: int = 8,
    capital_utilization_pct: float = 0.95,
    max_lots_per_trade: int = 0,
    option_execution_mode: str = OPTION_EXECUTION_BUY_ONLY,
) -> dict[str, Any]:
    """Public wrapper — backtest one SMC strategy by internal id."""
    return _run_single_strategy(
        candles,
        strategy_id,
        lot_size,
        capital,
        instrument_key=instrument_key,
        params=params,
        max_loss_per_day=max_loss_per_day,
        max_trades_per_day=max_trades_per_day,
        capital_utilization_pct=capital_utilization_pct,
        max_lots_per_trade=max_lots_per_trade,
        option_execution_mode=option_execution_mode,
    )


def _summarize(
    trades: list[SMCTrade],
    equity_curve: list[dict],
    capital: float,
    strategy_id: str,
    bars_processed: int,
    params: dict[str, Any],
) -> dict[str, Any]:
    label = SMC_REGISTRY.get(strategy_id, {}).get("label", strategy_id)
    if not trades:
        empty = _empty(strategy_id, "No trades generated", bars_processed, capital=capital)
        empty["params"] = params
        return empty

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades)
    win_rate = len(wins) / len(trades) * 100
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss else gross_profit
    avg_win = gross_profit / len(wins) if wins else 0
    avg_loss = sum(t.pnl for t in losses) / len(losses) if losses else 0
    avg_rr = sum(t.risk_reward for t in trades) / len(trades)
    avg_hold = sum(t.duration_bars for t in trades) / len(trades)

    peak = capital
    max_dd = 0
    for point in equity_curve:
        eq = point["equity"]
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)

    consistency = win_rate * 0.4 + min(profit_factor, 3) / 3 * 30 + (100 - min(max_dd / max(capital * 0.01, 1), 100)) * 0.3
    final_equity = equity_curve[-1]["equity"] if equity_curve else capital + total_pnl

    return {
        "status": "completed",
        "strategy_id": strategy_id,
        "strategy_label": label,
        "initial_capital": round(capital, 2),
        "final_capital": round(max(0.0, final_equity), 2),
        "total_trades": len(trades),
        "win_rate": round(win_rate, 2),
        "total_pnl": round(total_pnl, 2),
        "max_drawdown": round(max_dd, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_profit_win": round(avg_win, 2),
        "avg_loss_loss": round(avg_loss, 2),
        "avg_trade_pnl": round(total_pnl / len(trades), 2),
        "avg_risk_reward": round(avg_rr, 2),
        "avg_trade_duration_bars": round(avg_hold, 1),
        "avg_hold_minutes": round(avg_hold, 1),
        "consistency_score": round(consistency, 1),
        "bars_processed": bars_processed,
        "params": params,
        "equity_curve": equity_curve,
        "trades": [
            {
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "signal_type": t.signal_type,
                "entry": t.entry,
                "exit": t.exit,
                "pnl": t.pnl,
                "result": t.result,
                "duration_bars": t.duration_bars,
                "exit_reason": t.exit_reason,
                "strategy_id": t.strategy_id,
                "risk_reward": t.risk_reward,
            }
            for t in trades
        ],
    }


def _empty(strategy_id: str, message: str, bars_processed: int = 0, capital: float = 0) -> dict[str, Any]:
    return {
        "status": "completed",
        "message": message,
        "strategy_id": strategy_id,
        "strategy_label": SMC_REGISTRY.get(strategy_id, {}).get("label", strategy_id),
        "initial_capital": round(capital, 2),
        "final_capital": round(capital, 2),
        "total_trades": 0,
        "win_rate": 0,
        "total_pnl": 0,
        "max_drawdown": 0,
        "profit_factor": 0,
        "avg_risk_reward": 0,
        "avg_trade_duration_bars": 0,
        "consistency_score": 0,
        "bars_processed": bars_processed,
        "equity_curve": [],
        "trades": [],
    }


def _rank_key(row: dict[str, Any]) -> float:
    """Composite rank: net return, low drawdown, consistency."""
    pnl = float(row.get("total_pnl") or 0)
    dd = float(row.get("max_drawdown") or 1)
    pf = float(row.get("profit_factor") or 0)
    wr = float(row.get("win_rate") or 0)
    trades = int(row.get("total_trades") or 0)
    if trades < 3:
        return -9999
    dd_penalty = pnl / max(dd, 1) if dd else pnl
    return pnl * 0.45 + dd_penalty * 0.25 + pf * 100 * 0.15 + wr * 0.15


def run_smc_strategy_comparison(
    candles: pd.DataFrame,
    lot_size: int,
    capital: float,
    *,
    instrument_key: str = "nifty50",
    max_loss_per_day: float = 5000,
    max_trades_per_day: int = 8,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Backtest all three SMC strategies and produce ranking table."""
    results: list[dict[str, Any]] = []
    for sid in SMC_STRATEGY_IDS:
        result = _run_single_strategy(
            candles,
            sid,
            lot_size,
            capital,
            instrument_key=instrument_key,
            params=params,
            max_loss_per_day=max_loss_per_day,
            max_trades_per_day=max_trades_per_day,
        )
        results.append(result)

    ranked = sorted(results, key=_rank_key, reverse=True)
    for rank, row in enumerate(ranked, start=1):
        row["rank"] = rank
        row["composite_score"] = round(_rank_key(row), 2)

    best = ranked[0] if ranked else None
    explanation = _explain_best(best, ranked)

    return {
        "status": "completed",
        "strategy_family": "smc",
        "instrument": instrument_key,
        "bars_loaded": len(candles),
        "strategies": results,
        "ranking_table": [
            {
                "rank": r["rank"],
                "strategy_id": r["strategy_id"],
                "strategy_label": r.get("strategy_label"),
                "win_rate": r.get("win_rate"),
                "total_pnl": r.get("total_pnl"),
                "max_drawdown": r.get("max_drawdown"),
                "avg_risk_reward": r.get("avg_risk_reward"),
                "profit_factor": r.get("profit_factor"),
                "avg_hold_minutes": r.get("avg_hold_minutes"),
                "total_trades": r.get("total_trades"),
                "composite_score": r.get("composite_score"),
            }
            for r in ranked
        ],
        "best_strategy": best,
        "best_strategy_id": best.get("strategy_id") if best else None,
        "best_strategy_label": best.get("strategy_label") if best else None,
        "recommendation": _live_recommendation(best),
        "explanation": explanation,
    }


def _explain_best(best: dict[str, Any] | None, ranked: list[dict[str, Any]]) -> str:
    if not best or best.get("total_trades", 0) < 1:
        return "Insufficient trades across SMC strategies on this data window. Try a longer range or lower volume threshold."
    sid = best.get("strategy_id", "")
    parts = [
        f"{best.get('strategy_label')} ranked #1 with ₹{best.get('total_pnl')} net P&L, "
        f"{best.get('win_rate')}% win rate, and {best.get('profit_factor')} profit factor.",
    ]
    if sid == "smc_fvg_ob_bos":
        parts.append("Trend-aligned OB/FVG retests with 15m bias produced cleaner continuation entries.")
    elif sid == "smc_liquidity_sweep":
        parts.append("Liquidity sweeps with M/W reversals captured mean-reversion after stop hunts.")
    elif sid == "smc_orb_fvg":
        parts.append("Opening range breakouts with FVG pullbacks offered early-session momentum with defined risk.")
    if len(ranked) > 1:
        second = ranked[1]
        gap = float(best.get("total_pnl") or 0) - float(second.get("total_pnl") or 0)
        parts.append(f"Led #{2} by ₹{round(gap, 2)} on this sample.")
    return " ".join(parts)


def _live_recommendation(best: dict[str, Any] | None) -> dict[str, Any]:
    if not best:
        return {"strategy_family": "smc", "fixed_strategy_id": "smc_fvg_ob_bos", "strategy_mode": "manual"}
    return {
        "strategy_family": "smc",
        "strategy_mode": "manual",
        "fixed_strategy_id": best.get("strategy_id"),
        "smc_params": best.get("params") or DEFAULT_SMC_PARAMS,
        "paper_mode_first": True,
        "notes": "Run paper mode for 2–3 sessions before enabling live auto-trading.",
    }


OPT_GRID: dict[str, list[float | int]] = {
    "stop_atr_mult": [0.8, 1.0, 1.2],
    "target_atr_mult": [1.4, 1.6, 1.8, 2.0],
    "trailing_atr_mult": [0.5, 0.75, 1.0],
    "entry_buffer_pct": [0.05, 0.08, 0.12],
    "volume_min": [1.0, 1.15, 1.3],
}


def optimize_smc_params(
    candles: pd.DataFrame,
    strategy_id: str,
    lot_size: int,
    capital: float,
    *,
    instrument_key: str = "nifty50",
    max_combos: int = 16,
) -> dict[str, Any]:
    """Brute-force parameter search on the winning SMC strategy."""
    keys = list(OPT_GRID.keys())
    combos = list(itertools.product(*[OPT_GRID[k] for k in keys]))
    if len(combos) > max_combos:
        step = max(1, len(combos) // max_combos)
        combos = combos[::step][:max_combos]

    best_result = None
    best_score = -99999
    tested = 0

    for combo in combos:
        params = dict(zip(keys, combo))
        result = _run_single_strategy(
            candles,
            strategy_id,
            lot_size,
            capital,
            instrument_key=instrument_key,
            params=params,
        )
        tested += 1
        score = _rank_key(result)
        if score > best_score:
            best_score = score
            best_result = result

    return {
        "strategy_id": strategy_id,
        "combinations_tested": tested,
        "optimized_params": (best_result or {}).get("params") or DEFAULT_SMC_PARAMS,
        "optimized_metrics": best_result,
        "best_score": round(best_score, 2),
    }


def run_full_smc_pipeline(
    candles: pd.DataFrame,
    lot_size: int,
    capital: float,
    *,
    instrument_key: str = "nifty50",
    optimize: bool = True,
    max_loss_per_day: float = 5000,
    max_trades_per_day: int = 8,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare all SMC strategies, optimize winner, return full report."""
    comparison = run_smc_strategy_comparison(
        candles,
        lot_size,
        capital,
        instrument_key=instrument_key,
        max_loss_per_day=max_loss_per_day,
        max_trades_per_day=max_trades_per_day,
        params=params,
    )
    best_id = comparison.get("best_strategy_id")
    optimization = None
    if optimize and best_id:
        optimization = optimize_smc_params(
            candles,
            best_id,
            lot_size,
            capital,
            instrument_key=instrument_key,
        )
        if optimization.get("optimized_metrics"):
            comparison["best_strategy"] = optimization["optimized_metrics"]
            comparison["optimized_params"] = optimization["optimized_params"]
            comparison["recommendation"]["smc_params"] = optimization["optimized_params"]
            comparison["recommendation"]["fixed_strategy_id"] = best_id

    comparison["optimization"] = optimization
    return comparison
