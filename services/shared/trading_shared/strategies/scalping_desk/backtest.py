"""Historical backtest runner for scalping desk strategy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from trading_shared.strategies.scalping_desk.ai_decision import compute_ai_targets
from trading_shared.strategies.scalping_desk.daily_stop import evaluate_ai_daily_stop
from trading_shared.strategies.scalping_desk.engine import (
    enrich_candles,
    estimate_option_mark_premium,
    max_hold_bars,
    should_exit,
    should_exit_index,
)
from trading_shared.strategies.scalping_desk.strategy_catalog import (
    STRATEGY_CATALOG,
    catalog_entry,
    default_strategy_settings,
)
from trading_shared.strategies.scalping_desk.strategy_selector import select_and_evaluate, select_from_catalog
from trading_shared.strategies.scalping_desk.capital_utilization import (
    backtest_option_trade_pnl,
    backtest_size_for_bar,
)
from trading_shared.strategies.scalping_desk.option_execution import (
    OPTION_EXECUTION_BUY_AND_SELL,
    OPTION_EXECUTION_BUY_ONLY,
    adapt_signal_for_execution,
    backtest_sell_margin_lots,
    should_exit_option_position,
)

MAX_BACKTEST_BARS = 25000  # ~66 trading days of 1m bars
BACKTEST_LOOKBACK = 60
EQUITY_CURVE_STEP = 15
MIN_BARS_BETWEEN_TRADES = 8
ENTRY_SCAN_EVERY = 1


@dataclass
class BacktestTrade:
    entry_time: str
    exit_time: str
    signal_type: str
    entry: float
    exit: float
    pnl: float
    result: str
    duration_bars: int
    exit_reason: str = ""
    target_inr: float = 0
    strategy_id: str = ""
    strategy_code: str = ""
    lots: int = 1
    capital_deployed: float = 0


def _backtest_config_for_code(strategy_code: str, instrument_key: str) -> dict[str, Any]:
    entry = catalog_entry(strategy_code)
    if not entry:
        raise ValueError(f"Unknown strategy code: {strategy_code}")
    settings = default_strategy_settings(instrument_key)
    for code in list(settings.keys()):
        settings[code] = {"enabled": False, "execution_mode": "live"}
    settings[strategy_code] = {"enabled": True, "execution_mode": "live"}
    return {
        "strategy_mode": "manual",
        "fixed_strategy_code": strategy_code,
        "fixed_strategy_id": entry["id"],
        "strategy_family": entry["family"],
        "strategy_settings": settings,
    }


def run_strategy_backtest(
    candles: pd.DataFrame,
    timeframe: str,
    lot_size: int,
    capital: float,
    *,
    strategy_code: str,
    max_loss_per_day: float = 5000,
    max_trades_per_day: int = 3,
    instrument_key: str = "nifty50",
    params: dict[str, Any] | None = None,
    evaluation_days: int | None = None,
    ai_entry: bool = False,
    ai_exit: bool = False,
    capital_utilization_pct: float = 0.95,
    max_lots_per_trade: int = 0,
    option_execution_mode: str = OPTION_EXECUTION_BUY_ONLY,
) -> dict[str, Any]:
    """Backtest one catalog strategy by its stable code."""
    entry = catalog_entry(strategy_code)
    if not entry:
        return _empty_result(f"Unknown strategy code: {strategy_code}", capital=capital)
    if instrument_key not in entry.get("instruments", []):
        return _empty_result(f"{strategy_code} is not available on {instrument_key}", capital=capital)

    bt_params = dict(params or {})
    if strategy_code == "SCALP-BT-003" and instrument_key == "banknifty":
        from trading_shared.strategies.scalping_desk.ema_crossover_tuning import (
            EMA_CROSSOVER_BANK_DEFAULTS,
            merge_ema_crossover_params,
        )

        merged = merge_ema_crossover_params(bt_params, "banknifty")
        # Drop stale blocking filters from older saved desk configs.
        if float(merged.get("ema_vol_min") or 0) > 0 or float(merged.get("ema_min_separation_pct") or 0) > 0:
            merged = dict(EMA_CROSSOVER_BANK_DEFAULTS)
        bt_params = {**bt_params, "ema_crossover": merged}

    if strategy_code == "SCALP-BT-002" and instrument_key == "banknifty":
        from trading_shared.strategies.scalping_desk.orb_breakout_tuning import merge_orb_params

        bt_params = {**bt_params, "orb_breakout": merge_orb_params(bt_params, "banknifty")}

    if strategy_code == "SCALP-BT-004" and instrument_key == "nifty50":
        from trading_shared.strategies.scalping_desk.orb_breakout_tuning import (
            ORB_BREAKOUT_NIFTY_DEFAULTS,
            merge_orb_params,
        )

        merged = merge_orb_params(bt_params, "nifty50")
        # Drop stale blocking filters from older saved desk configs (pre-v21 retune).
        # Prior-inside + morning-only cutoff collapses the strategy to ~1 trade.
        prior = str(merged.get("orb_prior_mode") or "").lower().strip()
        require_inside = bool(merged.get("orb_require_inside_or", False)) or prior in (
            "close_inside",
            "inside",
            "a",
            "b",
            "close",
        )
        morning_only = int(merged.get("orb_entry_cutoff_min") or 0) <= (10 * 60 + 30)
        if require_inside or morning_only:
            merged = dict(ORB_BREAKOUT_NIFTY_DEFAULTS)
        bt_params = {**bt_params, "orb_breakout": merged}

    if strategy_code == "SCALP-AD-005" and instrument_key == "banknifty":
        from trading_shared.strategies.scalping_desk.momentum_burst_tuning import merge_momentum_burst_params

        merged = merge_momentum_burst_params(bt_params)
        bt_params = {**bt_params, "momentum_burst": merged}

    if strategy_code == "SCALP-AD-006" and instrument_key == "banknifty":
        from trading_shared.strategies.scalping_desk.vwap_bounce_tuning import merge_vwap_bounce_params

        merged = merge_vwap_bounce_params(bt_params, "banknifty")
        bt_params = {**bt_params, "vwap_bounce": merged}

    if strategy_code == "SCALP-AD-002" and instrument_key == "nifty50":
        from trading_shared.strategies.scalping_desk.vwap_bounce_tuning import merge_vwap_bounce_params

        merged = merge_vwap_bounce_params(bt_params, "nifty50")
        bt_params = {**bt_params, "vwap_bounce": merged}

    if strategy_code == "SCALP-SMC-006" and instrument_key == "banknifty":
        from trading_shared.strategies.scalping_desk.smc_orb_fvg_tuning import merge_smc_orb_fvg_params

        bt_params = merge_smc_orb_fvg_params(bt_params, "banknifty")

    if strategy_code == "SCALP-SMC-003" and instrument_key == "nifty50":
        from trading_shared.strategies.scalping_desk.smc_orb_fvg_tuning import merge_smc_orb_fvg_params

        bt_params = merge_smc_orb_fvg_params(bt_params, "nifty50")

    if entry["family"] == "smc":
        from trading_shared.strategies.scalping_desk.smc_backtest import run_single_smc_backtest

        # Live stream evaluates every bar; smc_entry_scan_every is for offline OFAT only.
        smc_params = {**bt_params, "smc_entry_scan_every": 1}
        result = run_single_smc_backtest(
            candles,
            entry["id"],
            lot_size,
            capital,
            instrument_key=instrument_key,
            params=smc_params,
            max_loss_per_day=max_loss_per_day,
            max_trades_per_day=max_trades_per_day,
            capital_utilization_pct=capital_utilization_pct,
            max_lots_per_trade=max_lots_per_trade,
            option_execution_mode=option_execution_mode,
            ai_entry=ai_entry,
        )
    else:
        result = run_backtest(
            candles,
            timeframe,
            lot_size,
            capital,
            max_loss_per_day=max_loss_per_day,
            max_trades_per_day=max_trades_per_day,
            instrument_key=instrument_key,
            strategy_code=strategy_code,
            params=bt_params,
            evaluation_days=evaluation_days,
            ai_entry=ai_entry,
            ai_exit=ai_exit,
            capital_utilization_pct=capital_utilization_pct,
            option_execution_mode=option_execution_mode,
        )

    result["strategy_code"] = strategy_code
    result["ai_entry"] = ai_entry
    result["ai_exit"] = ai_exit
    result["strategy_label"] = entry["label"]
    result["strategy_family"] = entry["family"]
    return result


def _trade_day(ts: str) -> str:
    return ts[:10] if len(ts) >= 10 else "unknown"


def run_backtest(
    candles: pd.DataFrame,
    timeframe: str,
    lot_size: int,
    capital: float,
    *,
    max_loss_per_day: float = 5000,
    max_trades_per_day: int = 3,
    instrument_key: str = "nifty50",
    strategy_mode: str = "auto",
    fixed_strategy_id: str | None = None,
    strategy_family: str = "adaptive",
    strategy_code: str | None = None,
    params: dict[str, Any] | None = None,
    evaluation_days: int | None = None,
    ai_entry: bool = False,
    ai_exit: bool = False,
    capital_utilization_pct: float = 0.95,
    max_lots_per_trade: int = 0,
    option_execution_mode: str = OPTION_EXECUTION_BUY_ONLY,
) -> dict[str, Any]:
    """
    Replay scalping rules on historical OHLCV candles.
    option_execution_mode: buy_only (BUY CE/PE) or buy_and_sell (SELL PE/CE on same setups).
    """
    if candles.empty or len(candles) < 30:
        return _empty_result("Insufficient candle history", capital=capital)

    frame = candles.reset_index(drop=True)
    if len(frame) > MAX_BACKTEST_BARS:
        frame = frame.tail(MAX_BACKTEST_BARS).reset_index(drop=True)

    data = enrich_candles(frame)
    trades: list[BacktestTrade] = []
    equity = capital
    equity_curve = [{"index": 0, "equity": equity, "date": str(data.iloc[0].get("timestamp", 0))}]
    active = None
    last_exit_index = -MIN_BARS_BETWEEN_TRADES
    day_pnl: dict[str, float] = {}
    day_trades: dict[str, int] = {}
    day_wins: dict[str, int] = {}
    day_consecutive: dict[str, int] = {}
    day_stopped: dict[str, bool] = {}
    day_stop_count = 0

    empty_chain = {"rows": []}
    window = 30
    hold_limit = max_hold_bars(instrument_key)

    catalog_config = _backtest_config_for_code(strategy_code, instrument_key) if strategy_code else None
    code_meta = STRATEGY_CATALOG.get(strategy_code or "", {})
    filter_backtest_session = True
    session_mask: list[bool] = []
    if filter_backtest_session:
        from trading_shared.strategies.scalping_desk.battle_tested_scalp import precompute_battle_session_mask

        session_mask = precompute_battle_session_mask(data, instrument_key)

    for i in range(window, len(data)):
        row = data.iloc[i]
        ts = str(row.get("timestamp", i))
        spot = float(row["close"])
        day = _trade_day(ts)

        if active:
            bars_held = i - active["entry_index"]
            entry_premium = float(active.get("entry") or 0)
            entry_spot = float(active.get("entry_spot") or spot)
            current_premium = estimate_option_mark_premium(
                entry_premium, active["signal_type"], entry_spot, spot
            )
            exit_hit, reason = should_exit_option_position(
                order_side=str(active.get("order_side") or "BUY"),
                signal_type=active["signal_type"],
                current_ltp=current_premium,
                entry=entry_premium,
                target=float(active.get("target") or entry_premium * 1.08),
                stoploss=float(active.get("stoploss") or entry_premium * 0.88),
                indicators=active.get("indicators") or {},
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
                )
            if ai_exit and not exit_hit:
                battle_family = (catalog_config or {}).get("strategy_family") == "battle" or (
                    strategy_code or ""
                ).startswith("SCALP-BT")
                if not battle_family:
                    from trading_shared.strategies.scalping_desk.ai_decision import evaluate_ai_exit

                    hold_segment = data.iloc[active["entry_index"] : i + 1]
                    move_now = spot - active["entry_spot"]
                    if active["signal_type"] == "PUT":
                        move_now = -move_now
                    stop_pts = float(active.get("stop_pts") or 0)
                    ai_exit_dec = evaluate_ai_exit(
                        active,
                        spot,
                        bars_held,
                        trailing=None,
                        df=hold_segment if move_now <= -stop_pts * 0.45 else None,
                        vwap=float(row.get("vwap") or spot),
                    )
                    if ai_exit_dec.get("action") == "EXIT":
                        exit_hit = True
                        reason = ai_exit_dec.get("mode") or "ai_exit"
            if exit_hit or reason:
                trade_lots = int(active.get("lots") or 1)
                pnl = backtest_option_trade_pnl(
                    entry_premium,
                    current_premium,
                    lot_size,
                    trade_lots,
                    order_side=str(active.get("order_side") or "BUY"),
                )
                equity += pnl
                day_pnl[day] = day_pnl.get(day, 0.0) + pnl
                day_trades[day] = day_trades.get(day, 0) + 1
                if pnl > 0:
                    day_wins[day] = day_wins.get(day, 0) + 1
                    day_consecutive[day] = day_consecutive.get(day, 0) + 1
                else:
                    day_consecutive[day] = 0
                exit_ctx = active.get("market_context") if active else {}
                pseudo_state = {
                    "trades_today": day_trades.get(day, 0),
                    "wins_today": day_wins.get(day, 0),
                    "consecutive_wins": day_consecutive.get(day, 0),
                    "daily_pnl": day_pnl.get(day, 0.0),
                }
                stop_decision = evaluate_ai_daily_stop(
                    pseudo_state,
                    {"capital": capital, "max_trades_per_day": max_trades_per_day},
                    exit_ctx,
                )
                if stop_decision.get("stop_trading"):
                    if not day_stopped.get(day):
                        day_stop_count += 1
                    day_stopped[day] = True
                trades.append(
                    BacktestTrade(
                        entry_time=active["entry_time"],
                        exit_time=ts,
                        signal_type=active["signal_type"],
                        entry=active["entry_spot"],
                        exit=round(spot, 2),
                        pnl=round(pnl, 2),
                        result="Win" if pnl > 0 else "Loss",
                        duration_bars=bars_held,
                        exit_reason=reason or "unknown",
                        target_inr=active.get("target_inr", 0),
                        strategy_id=active.get("strategy_id", ""),
                        strategy_code=active.get("strategy_code", ""),
                        lots=trade_lots,
                        capital_deployed=round(active.get("capital_deployed") or 0, 2),
                    )
                )
                active = None
                last_exit_index = i

        daily_pnl = day_pnl.get(day, 0.0)
        trades_today = day_trades.get(day, 0)
        loss_breached = daily_pnl <= -abs(max_loss_per_day)
        trades_capped = max_trades_per_day > 0 and trades_today >= max_trades_per_day
        ai_stopped = day_stopped.get(day, False)

        scan_bar = (i - window) % ENTRY_SCAN_EVERY == 0
        if (
            scan_bar
            and active is None
            and i - last_exit_index >= MIN_BARS_BETWEEN_TRADES
            and not loss_breached
            and not trades_capped
            and not ai_stopped
        ):
            if filter_backtest_session:
                from trading_shared.strategies.scalping_desk.battle_tested_scalp import is_expiry_day

                if (session_mask and not session_mask[i]) or is_expiry_day(ts, instrument_key):
                    continue
            start = max(0, i + 1 - BACKTEST_LOOKBACK)
            segment = data.iloc[start : i + 1]
            if catalog_config:
                signal_obj, selection = select_from_catalog(
                    segment,
                    timeframe,
                    empty_chain,
                    lot_size,
                    instrument_key,
                    catalog_config,
                    params=params,
                    skip_session=True,
                    enriched=True,
                )
            else:
                signal_obj, selection = select_and_evaluate(
                    segment,
                    timeframe,
                    empty_chain,
                    lot_size,
                    instrument_key,
                    params=params,
                    strategy_mode=strategy_mode,
                    fixed_strategy_id=fixed_strategy_id,
                    strategy_family=strategy_family,
                    skip_session=True,
                    enriched=True,
                )
            if signal_obj:
                sig = adapt_signal_for_execution(signal_obj.to_dict(), option_execution_mode)
                context = {
                    "capital": capital,
                    "lot_size": lot_size,
                    "current_pnl": daily_pnl,
                    "trades_today": trades_today,
                    "max_loss_per_day": max_loss_per_day,
                    "max_trades_per_day": max_trades_per_day,
                }
                targets = compute_ai_targets(instrument_key, sig, context)
                if ai_entry:
                    battle_family = (catalog_config or {}).get("strategy_family") == "battle" or (
                        strategy_code or ""
                    ).startswith("SCALP-BT")
                    if not battle_family:
                        from trading_shared.strategies.scalping_desk.entry_signal_validator import (
                            validate_from_signal,
                            verdict_allows_entry,
                        )

                        validation = validate_from_signal(
                            instrument_key,
                            sig,
                            targets=targets,
                            timestamp=ts,
                        )
                        if validation.get("verdict") == "SKIP":
                            continue
                entry_spot = float(sig["indicators"].get("spot") or spot)
                entry_premium = float(sig.get("entry") or 0)
                if str(sig.get("order_side") or "BUY").upper() == "SELL":
                    _, deployable, premium = backtest_size_for_bar(
                        initial_capital=capital,
                        instrument_key=instrument_key,
                        spot=entry_spot,
                        day=day,
                        day_pnl=day_pnl,
                        utilization_pct=capital_utilization_pct,
                        option_premium=entry_premium if entry_premium > 0 else None,
                        max_lots=max_lots_per_trade,
                        current_equity=equity,
                    )
                    lots = backtest_sell_margin_lots(deployable, entry_spot, lot_size)
                    premium = entry_premium if entry_premium > 0 else premium
                else:
                    lots, deployable, premium = backtest_size_for_bar(
                        initial_capital=capital,
                        instrument_key=instrument_key,
                        spot=entry_spot,
                        day=day,
                        day_pnl=day_pnl,
                        utilization_pct=capital_utilization_pct,
                        option_premium=entry_premium if entry_premium > 0 else None,
                        max_lots=max_lots_per_trade,
                        current_equity=equity,
                    )
                if lots < 1:
                    continue
                active = {
                    **sig,
                    "entry_time": ts,
                    "entry_index": i,
                    "entry_spot": entry_spot,
                    "lots": lots,
                    "capital_deployed": round(lots * premium * lot_size, 2),
                    "stop_pts": targets["stop_pts"],
                    "target_pts": targets["target_pts"],
                    "target_inr": targets["target_inr"],
                    "max_hold_bars": targets.get("max_hold_bars") or sig["indicators"].get("max_hold_bars") or hold_limit,
                    "strategy_id": sig.get("strategy_id") or sig["indicators"].get("strategy_id", ""),
                    "strategy_code": strategy_code or selection.get("selected_strategy_code") or "",
                    "market_context": selection.get("market_context") or {},
                }

        if i % EQUITY_CURVE_STEP == 0 or i == len(data) - 1:
            equity_curve.append({"index": i, "equity": round(equity, 2), "date": ts})

    return _summarize(
        trades,
        equity_curve,
        capital,
        instrument_key,
        day_stop_count,
        len(data),
        strategy_code=strategy_code,
        strategy_label=code_meta.get("label"),
        evaluation_days=evaluation_days,
        ai_entry=ai_entry,
        ai_exit=ai_exit,
        capital_utilization_pct=capital_utilization_pct,
        option_execution_mode=option_execution_mode,
    )


def _filter_trades_by_days(trades: list[BacktestTrade], days: int) -> list[BacktestTrade]:
    if not days or not trades:
        return trades
    cutoff = (datetime.now() - timedelta(days=days)).date()
    filtered = []
    for t in trades:
        exit_day = _parse_trade_day(t.exit_time)
        if exit_day and exit_day >= cutoff:
            filtered.append(t)
    return filtered


def _parse_trade_day(ts: str):
    if not ts or len(ts) < 10:
        return None
    try:
        return datetime.strptime(ts[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _summarize(
    trades: list[BacktestTrade],
    equity_curve: list[dict],
    capital: float,
    instrument_key: str,
    ai_early_stops: int = 0,
    bars_processed: int = 0,
    *,
    strategy_code: str | None = None,
    strategy_label: str | None = None,
    evaluation_days: int | None = None,
    ai_entry: bool = False,
    ai_exit: bool = False,
    capital_utilization_pct: float = 0.95,
    option_execution_mode: str = OPTION_EXECUTION_BUY_ONLY,
) -> dict[str, Any]:
    if evaluation_days:
        trades = _filter_trades_by_days(trades, evaluation_days)
        if not trades:
            return _empty_result(
                f"No trades in last {evaluation_days} days",
                bars_processed=bars_processed,
                capital=capital,
            )
        # Rebuild equity curve from filtered trades
        equity = capital
        equity_curve = [{"index": 0, "equity": equity, "date": trades[0].entry_time[:10]}]
        for idx, t in enumerate(sorted(trades, key=lambda x: x.exit_time), start=1):
            equity += t.pnl
            equity_curve.append({"index": idx, "equity": round(equity, 2), "date": t.exit_time[:10]})
    if not trades:
        return _empty_result("No trades generated", bars_processed=bars_processed, capital=capital)

    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    total_pnl = sum(t.pnl for t in trades)
    win_rate = len(wins) / len(trades) * 100
    avg_win = sum(t.pnl for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t.pnl for t in losses) / len(losses) if losses else 0
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss else gross_profit

    returns = []
    prev_eq = capital
    for point in equity_curve[1:]:
        eq = point["equity"]
        if prev_eq > 0:
            returns.append((eq - prev_eq) / prev_eq)
        prev_eq = eq
    if len(returns) > 1:
        import statistics

        mean_r = statistics.mean(returns)
        std_r = statistics.pstdev(returns) or 1e-9
        sharpe = round((mean_r / std_r) * (252**0.5), 2)
    else:
        sharpe = 0.0

    peak = capital
    max_dd = 0
    for point in equity_curve:
        eq = point["equity"]
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)

    best = max(trades, key=lambda t: t.pnl)
    worst = min(trades, key=lambda t: t.pnl)
    avg_duration = sum(t.duration_bars for t in trades) / len(trades)
    avg_target_inr = sum(t.target_inr for t in trades) / len(trades) if trades else 0

    monthly: dict[str, dict] = {}
    for t in trades:
        month = t.exit_time[:7] if len(t.exit_time) >= 7 else "unknown"
        bucket = monthly.setdefault(month, {"trades": 0, "pnl": 0, "wins": 0})
        bucket["trades"] += 1
        bucket["pnl"] += t.pnl
        if t.pnl > 0:
            bucket["wins"] += 1

    monthly_rows = [
        {
            "month": m,
            "trades": v["trades"],
            "pnl": round(v["pnl"], 2),
            "win_rate": round(v["wins"] / v["trades"] * 100, 1) if v["trades"] else 0,
        }
        for m, v in sorted(monthly.items())
    ]

    return {
        "status": "completed",
        "strategy": strategy_code or "battle_tested_scalp_v5",
        "strategy_code": strategy_code,
        "strategy_label": strategy_label,
        "instrument": instrument_key,
        "initial_capital": round(capital, 2),
        "final_capital": round(equity_curve[-1]["equity"] if equity_curve else capital + total_pnl, 2),
        "capital_utilization_pct": capital_utilization_pct,
        "option_execution_mode": option_execution_mode,
        "total_trades": len(trades),
        "win_rate": round(win_rate, 2),
        "total_pnl": round(total_pnl, 2),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd / max(capital, 1) * 100, 2),
        "sharpe_ratio": sharpe,
        "profit_factor": round(profit_factor, 2),
        "avg_profit_win": round(avg_win, 2),
        "avg_loss_loss": round(avg_loss, 2),
        "avg_target_inr": round(avg_target_inr, 2),
        "ai_early_stop_days": ai_early_stops,
        "best_trade": {"pnl": best.pnl, "signal_type": best.signal_type},
        "worst_trade": {"pnl": worst.pnl, "signal_type": worst.signal_type},
        "avg_trade_duration_bars": round(avg_duration, 1),
        "max_hold_bars": max_hold_bars(instrument_key),
        "bars_processed": bars_processed,
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
                "target_inr": t.target_inr,
                "strategy_id": t.strategy_id,
                "strategy_code": t.strategy_code,
                "lots": t.lots,
                "capital_deployed": t.capital_deployed,
            }
            for t in trades
        ],
        "monthly_breakdown": monthly_rows,
        "evaluation_days": evaluation_days,
        "ai_entry": ai_entry,
        "ai_exit": ai_exit,
    }


def _empty_result(message: str, bars_processed: int = 0, capital: float = 0) -> dict[str, Any]:
    cap = round(float(capital or 0), 2)
    return {
        "status": "completed",
        "message": message,
        "total_trades": 0,
        "win_rate": 0,
        "total_pnl": 0,
        "max_drawdown": 0,
        "initial_capital": cap,
        "final_capital": cap,
        "profit_factor": 0,
        "avg_profit_win": 0,
        "avg_loss_loss": 0,
        "avg_trade_duration_bars": 0,
        "bars_processed": bars_processed,
        "equity_curve": [{"index": 0, "equity": cap, "date": ""}] if cap else [],
        "trades": [],
        "monthly_breakdown": [],
    }
