"""Bar-by-bar intraday backtest engine with transaction costs and risk-based sizing."""

from __future__ import annotations

import pandas as pd

from trading_shared.backtest.types import BacktestTrade
from trading_shared.strategies.intraday_desk.catalog import catalog_entry
from trading_shared.strategies.intraday_desk.session import (
    enrich_intraday_frame,
    is_force_exit_bar,
    position_qty,
    trading_date,
    transaction_cost,
)
from trading_shared.strategies.intraday_desk.strategies import get_strategy

WARMUP = 25
MAX_TRADES_PER_DAY = 3


def run_intraday_strategy_backtest(
    df: pd.DataFrame,
    strategy_code: str,
    symbol: str,
    *,
    initial_capital: float = 100_000.0,
    risk_pct: float = 1.0,
    ai_entry: bool = False,
    ai_exit: bool = False,
) -> dict:
    entry_meta = catalog_entry(strategy_code)
    if not entry_meta:
        raise ValueError(f"Unknown intraday strategy code: {strategy_code}")

    if len(df) < WARMUP + 5:
        raise ValueError(f"Insufficient bars ({len(df)}). Need at least {WARMUP + 5}.")

    prepared = enrich_intraday_frame(df)
    strategy = get_strategy(strategy_code=strategy_code)

    capital = initial_capital
    equity_curve: list[float] = []
    trades: list[BacktestTrade] = []
    position = None
    traded_days: set = set()
    daily_trade_count: dict = {}

    for i in range(WARMUP, len(prepared)):
        row = prepared.iloc[i]
        ts = row["timestamp"]
        day = trading_date(ts)

        if daily_trade_count.get(day, 0) >= MAX_TRADES_PER_DAY:
            equity_curve.append(round(capital, 2))
            continue

        if position is not None:
            exit_result = strategy.try_exit(position, prepared, i)
            exit_price = None
            exit_reason = ""

            if is_force_exit_bar(ts):
                exit_price = float(row["close"])
                exit_reason = "eod"
            elif exit_result:
                exit_price, exit_reason = exit_result

            if ai_exit and exit_price is None:
                from trading_shared.ai.trade_reasoning import evaluate_dynamic_exit

                segment = prepared.iloc[max(0, i - 29) : i + 1]
                dynamic = evaluate_dynamic_exit(
                    engine="intraday",
                    side=position["side"],
                    entry=float(position["entry_price"]),
                    stop=float(position["stoploss"]),
                    target=float(position["target"]) if position.get("target") else None,
                    strategy=strategy_code,
                    current=float(row["close"]),
                    candles=segment,
                    vwap=float(row.get("vwap") or row["close"]),
                    bar_time=ts,
                )
                pnl_r = (
                    (float(row["close"]) - float(position["entry_price"]))
                    / abs(float(position["entry_price"]) - float(position["stoploss"]))
                    if position["side"] == "BUY"
                    else (float(position["entry_price"]) - float(row["close"]))
                    / abs(float(position["entry_price"]) - float(position["stoploss"]))
                )
                if dynamic.get("should_exit") and dynamic.get("confidence_score", 0) >= 95:
                    exit_price = float(row["close"])
                    exit_reason = "ai_dynamic_exit"

            if exit_price is not None:
                gross = (
                    (exit_price - position["entry_price"]) * position["qty"]
                    if position["side"] == "BUY"
                    else (position["entry_price"] - exit_price) * position["qty"]
                )
                costs = transaction_cost(position["entry_price"], exit_price, position["qty"])
                pnl = round(gross - costs, 2)
                notional = position["entry_price"] * position["qty"]
                trades.append(
                    BacktestTrade(
                        entry_ts=position["entry_ts"],
                        exit_ts=str(ts),
                        side=position["side"],
                        symbol=symbol,
                        entry_price=position["entry_price"],
                        exit_price=round(exit_price, 2),
                        qty=position["qty"],
                        pnl=pnl,
                        return_pct=round(pnl / notional * 100, 2) if notional else 0.0,
                        stoploss=position["stoploss"],
                        target=position["target"],
                    )
                )
                capital += pnl
                position = None
        else:
            traded_today = day in traded_days
            signal = strategy.try_entry(prepared, i, traded_today)
            if signal and not is_force_exit_bar(ts):
                if ai_entry:
                    from trading_shared.ai.trade_reasoning import evaluate_entry_confirmation

                    segment = prepared.iloc[max(0, i - 19) : i + 1]
                    confirmation = evaluate_entry_confirmation(
                        strategy=strategy_code,
                        side=signal.side,
                        entry=float(signal.entry),
                        stop=float(signal.stoploss),
                        target=float(signal.target) if signal.target else None,
                        candles=segment,
                        timeframe="5m",
                        rsi=float(row.get("rsi14") or 50),
                        atr=float(row.get("atr") or 0) or None,
                        vwap=float(row.get("vwap") or signal.entry),
                        volume_ratio=float(row.get("volume_ratio") or 1),
                    )
                    if confirmation.get("confidence_score", 100) < 20:
                        equity_curve.append(round(capital, 2))
                        continue
                qty = position_qty(capital, signal.entry, signal.stoploss, risk_pct)
                if qty > 0:
                    position = {
                        "entry_ts": str(ts),
                        "side": signal.side,
                        "entry_price": round(signal.entry, 2),
                        "qty": qty,
                        "stoploss": signal.stoploss,
                        "target": signal.target,
                        "trailing_pct": signal.trailing_pct,
                        "strategy_code": strategy_code,
                    }
                    traded_days.add(day)
                    daily_trade_count[day] = daily_trade_count.get(day, 0) + 1

        equity_curve.append(round(capital, 2))

    return _build_result(
        initial_capital, capital, equity_curve, trades, strategy_code, entry_meta["label"], ai_entry, ai_exit
    )


def _build_result(
    initial_capital: float,
    capital: float,
    equity_curve: list[float],
    trades: list[BacktestTrade],
    strategy_code: str,
    strategy_label: str,
    ai_entry: bool = False,
    ai_exit: bool = False,
) -> dict:
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else round(gross_profit, 2)

    peak = equity_curve[0] if equity_curve else capital
    max_dd = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak * 100)

    total_pnl = round(capital - initial_capital, 2)
    return {
        "initial_capital": initial_capital,
        "final_capital": round(capital, 2),
        "equity_curve": equity_curve,
        "trades": [t.to_dict() for t in trades],
        "total_trades": len(trades),
        "win_rate": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "max_drawdown": round(max_dd, 2),
        "profit_factor": profit_factor,
        "total_pnl": total_pnl,
        "avg_trade_pnl": round(total_pnl / len(trades), 2) if trades else 0.0,
        "strategy_code": strategy_code,
        "strategy_label": strategy_label,
        "cost_model": "0.03% brokerage + 0.01% slippage per leg",
        "ai_entry": ai_entry,
        "ai_exit": ai_exit,
    }


def _merge_equity_curve(initial_capital: float, trade_lists: list[list[dict]]) -> list[float]:
    events: list[tuple[str, float]] = []
    for trades in trade_lists:
        for trade in trades:
            events.append((str(trade["exit_ts"]), float(trade["pnl"])))
    events.sort(key=lambda item: item[0])
    equity = initial_capital
    curve = [round(equity, 2)]
    for _, pnl in events:
        equity += pnl
        curve.append(round(equity, 2))
    return curve


def run_intraday_universe_backtest(
    loader,
    *,
    user_id: int,
    strategy_code: str,
    exchange: str,
    interval: str,
    from_date: str,
    to_date: str,
    use_demo_data: bool,
    initial_capital: float,
    risk_pct: float,
    top_n: int = 10,
    universe: list[str] | None = None,
    ai_entry: bool = False,
    ai_exit: bool = False,
) -> dict:
    """Screen Nifty 50 history, pick top names, and backtest each with split capital."""
    from trading_shared.strategies.intraday_desk.stock_picker import default_universe, rank_universe

    entry_meta = catalog_entry(strategy_code)
    if not entry_meta:
        raise ValueError(f"Unknown intraday strategy code: {strategy_code}")

    symbols = universe or default_universe()
    symbol_frames: list[tuple[str, pd.DataFrame]] = []
    data_source = "demo"

    for symbol in symbols:
        try:
            token, resolved = loader.resolve_token(symbol, None)
            df, source = loader.load(
                user_id=user_id,
                symbol=resolved,
                token=token,
                exchange=exchange,
                interval=interval,
                from_date=from_date,
                to_date=to_date,
                use_demo_data=use_demo_data,
            )
            if len(df) >= WARMUP + 5:
                symbol_frames.append((resolved, df))
                data_source = source
        except Exception:
            continue

    if not symbol_frames:
        raise ValueError("No symbols with sufficient historical data for screening.")

    ranked = rank_universe(symbol_frames, strategy_code)
    if not ranked:
        raise ValueError("Could not rank any symbols for the selected strategy.")

    picks = ranked[: max(1, min(top_n, len(ranked)))]
    pick_symbols = {row["symbol"] for row in picks}
    frame_map = {sym: df for sym, df in symbol_frames if sym in pick_symbols}

    capital_each = initial_capital / len(picks)
    stock_results: list[dict] = []
    all_trades: list[dict] = []

    for pick in picks:
        symbol = pick["symbol"]
        df = frame_map.get(symbol)
        if df is None:
            continue
        result = run_intraday_strategy_backtest(
            df=df,
            strategy_code=strategy_code,
            symbol=symbol,
            initial_capital=capital_each,
            risk_pct=risk_pct,
            ai_entry=ai_entry,
            ai_exit=ai_exit,
        )
        stock_results.append(
            {
                "symbol": symbol,
                "score": pick["score"],
                "screen_score": pick.get("screen_score"),
                "preview_win_rate": pick.get("preview_win_rate"),
                "total_trades": result["total_trades"],
                "win_rate": result["win_rate"],
                "total_pnl": result["total_pnl"],
                "profit_factor": result["profit_factor"],
            }
        )
        all_trades.extend(result["trades"])

    if not stock_results:
        raise ValueError("Backtest produced no results for picked symbols.")

    stock_results.sort(key=lambda row: row["total_pnl"], reverse=True)
    total_pnl = round(sum(row["total_pnl"] for row in stock_results), 2)
    final_capital = round(initial_capital + total_pnl, 2)
    total_trades = sum(row["total_trades"] for row in stock_results)
    wins = len([t for t in all_trades if t["pnl"] > 0])
    gross_profit = sum(t["pnl"] for t in all_trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in all_trades if t["pnl"] <= 0))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else round(gross_profit, 2)
    equity_curve = _merge_equity_curve(initial_capital, [all_trades])

    peak = equity_curve[0]
    max_dd = 0.0
    for value in equity_curve:
        if value > peak:
            peak = value
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak * 100)

    all_trades.sort(key=lambda t: str(t["exit_ts"]))

    base = _build_result(
        initial_capital,
        final_capital,
        equity_curve,
        [],
        strategy_code,
        entry_meta["label"],
        ai_entry,
        ai_exit,
    )
    base.update(
        {
            "trades": all_trades,
            "total_trades": total_trades,
            "win_rate": round(wins / total_trades * 100, 2) if total_trades else 0.0,
            "profit_factor": profit_factor,
            "total_pnl": total_pnl,
            "avg_trade_pnl": round(total_pnl / total_trades, 2) if total_trades else 0.0,
            "max_drawdown": round(max_dd, 2),
            "picked_stocks": stock_results,
            "universe_screened": len(symbol_frames),
            "top_n": len(stock_results),
            "data_source": data_source,
            "selection_mode": "auto",
        }
    )
    return base
