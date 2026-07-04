"""Portfolio swing backtest — multi-stock, multi-position, delivery costs."""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from trading_shared.backtest.types import BacktestTrade
from trading_shared.market.scrip_master import NIFTY50_SYMBOLS
from trading_shared.strategies.swing_desk.catalog import catalog_entry
from trading_shared.strategies.swing_desk.session import (
    WARMUP_BARS,
    enrich_swing_frame,
    position_notional,
    position_qty,
    swing_entry_cost,
    swing_exit_cost,
    swing_transaction_cost,
)
from trading_shared.strategies.swing_desk.strategies import get_strategy


def run_swing_portfolio_backtest(
    symbol_frames: dict[str, pd.DataFrame],
    strategy_code: str,
    *,
    initial_capital: float = 100_000.0,
    risk_pct: float = 1.0,
    max_open_positions: int = 5,
    ai_entry: bool = False,
    ai_exit: bool = False,
) -> dict:
    """Run long-only swing strategy across multiple symbols with concurrent position cap."""
    entry_meta = catalog_entry(strategy_code)
    if not entry_meta:
        raise ValueError(f"Unknown swing strategy code: {strategy_code}")

    strategy = get_strategy(strategy_code=strategy_code)
    prepared: dict[str, pd.DataFrame] = {}
    for symbol, df in symbol_frames.items():
        if len(df) >= WARMUP_BARS:
            prepared[symbol] = enrich_swing_frame(df)

    if not prepared:
        raise ValueError("No symbols with sufficient daily history (need ~210 bars).")

    max_len = max(len(df) for df in prepared.values())
    cash = initial_capital
    positions: dict[str, dict] = {}
    trades: list[BacktestTrade] = []
    equity_curve: list[float] = []

    for bar_idx in range(WARMUP_BARS, max_len):
        # --- exits ---
        for symbol in list(positions.keys()):
            df = prepared.get(symbol)
            if df is None or bar_idx >= len(df):
                continue
            pos = positions[symbol]
            row = df.iloc[bar_idx]
            exit_result = strategy.try_exit(pos, df, bar_idx)
            exit_price = None
            exit_reason = None
            if exit_result:
                exit_price, exit_reason = exit_result
            if ai_exit and exit_price is None:
                from trading_shared.ai.trade_reasoning import evaluate_dynamic_exit

                segment = df.iloc[max(0, bar_idx - 29) : bar_idx + 1]
                dynamic = evaluate_dynamic_exit(
                    engine="swing",
                    side="BUY",
                    entry=float(pos["entry_price"]),
                    stop=float(pos["stoploss"]),
                    target=float(pos.get("target")) if pos.get("target") else None,
                    strategy=strategy_code,
                    current=float(row["close"]),
                    candles=segment,
                    bars_held=bar_idx - int(pos.get("entry_idx") or bar_idx),
                    max_hold_days=int(pos.get("max_hold_days") or 60),
                    bar_time=row.get("timestamp", bar_idx),
                )
                risk = abs(float(pos["entry_price"]) - float(pos["stoploss"])) or 1.0
                pnl_r = (float(row["close"]) - float(pos["entry_price"])) / risk
                if dynamic.get("should_exit") and dynamic.get("confidence_score", 0) >= 95:
                    exit_price = float(row["close"])
                    exit_reason = "ai_dynamic_exit"
                elif dynamic.get("should_tighten") and dynamic.get("revised_stop"):
                    pos["stoploss"] = dynamic["revised_stop"]
            if exit_price is None:
                continue
            gross = (exit_price - pos["entry_price"]) * pos["qty"]
            exit_cost = swing_exit_cost(exit_price, pos["qty"])
            entry_cost = swing_entry_cost(pos["entry_price"], pos["qty"])
            pnl = round(gross - entry_cost - exit_cost, 2)
            cash += exit_price * pos["qty"] - exit_cost
            notional = pos["entry_price"] * pos["qty"]
            trades.append(
                BacktestTrade(
                    entry_ts=pos["entry_ts"],
                    exit_ts=str(row.get("timestamp", bar_idx)),
                    side="BUY",
                    symbol=symbol,
                    entry_price=pos["entry_price"],
                    exit_price=round(exit_price, 2),
                    qty=pos["qty"],
                    pnl=pnl,
                    return_pct=round(pnl / notional * 100, 2) if notional else 0.0,
                    stoploss=pos["stoploss"],
                    target=pos.get("target", 0),
                )
            )
            del positions[symbol]

        equity = cash + sum(
            float(prepared[s].iloc[min(bar_idx, len(prepared[s]) - 1)]["close"]) * positions[s]["qty"]
            for s in positions
            if s in prepared
        )

        # --- entries (if slots available) ---
        if len(positions) < max_open_positions:
            candidates: list[tuple[float, str, object]] = []
            for symbol, df in prepared.items():
                if symbol in positions or bar_idx >= len(df):
                    continue
                signal = strategy.try_entry(df, bar_idx, in_position=False)
                if signal:
                    if ai_entry:
                        from trading_shared.ai.trade_reasoning import evaluate_entry_confirmation

                        row = df.iloc[bar_idx]
                        segment = df.iloc[max(0, bar_idx - 19) : bar_idx + 1]
                        confirmation = evaluate_entry_confirmation(
                            strategy=strategy_code,
                            side="BUY",
                            entry=float(signal.entry),
                            stop=float(signal.stoploss),
                            target=None,
                            candles=segment,
                            timeframe="1d",
                            rsi=float(row.get("rsi14") or 50),
                            atr=float(row.get("atr") or 0) or None,
                            vwap=float(row.get("close") or signal.entry),
                            volume_ratio=float(row.get("volume_ratio") or 1),
                        )
                        if confirmation.get("confidence_score", 100) < 20:
                            continue
                    score = float(df.iloc[bar_idx]["volume"])
                    candidates.append((score, symbol, signal))

            candidates.sort(key=lambda item: item[0], reverse=True)
            slots = max_open_positions - len(positions)

            for _, symbol, signal in candidates[:slots]:
                df = prepared[symbol]
                row = df.iloc[bar_idx]
                entry = round(signal.entry, 2)
                qty = position_qty(equity, entry, signal.stoploss, risk_pct)
                notional = position_notional(qty, entry)
                entry_cost = swing_entry_cost(entry, qty)
                total_outlay = notional + entry_cost
                if qty <= 0 or total_outlay > cash:
                    unit_cost = entry * (1 + 0.0005)  # approx entry + leg costs
                    affordable = int((cash * 0.99) // unit_cost) if unit_cost > 0 else 0
                    if affordable <= 0:
                        continue
                    qty = affordable
                    notional = position_notional(qty, entry)
                    entry_cost = swing_entry_cost(entry, qty)
                    total_outlay = notional + entry_cost

                cash -= total_outlay
                positions[symbol] = {
                    "entry_idx": bar_idx,
                    "entry_ts": str(row.get("timestamp", bar_idx)),
                    "entry_price": entry,
                    "qty": qty,
                    "stoploss": signal.stoploss,
                    "peak_close": entry,
                    "trailing_pct": signal.trailing_pct,
                    "use_chandelier": signal.use_chandelier,
                    "chandelier_atr_mult": signal.chandelier_atr_mult,
                    "max_hold_days": signal.max_hold_days,
                    "target": 0,
                    "strategy_code": strategy_code,
                }

        equity = cash + sum(
            float(prepared[s].iloc[min(bar_idx, len(prepared[s]) - 1)]["close"]) * positions[s]["qty"]
            for s in positions
            if s in prepared
        )
        equity_curve.append(round(equity, 2))

    # Flat remaining at last bar
    for symbol, pos in list(positions.items()):
        df = prepared.get(symbol)
        if df is None:
            continue
        row = df.iloc[-1]
        exit_price = float(row["close"])
        gross = (exit_price - pos["entry_price"]) * pos["qty"]
        exit_cost = swing_exit_cost(exit_price, pos["qty"])
        entry_cost = swing_entry_cost(pos["entry_price"], pos["qty"])
        pnl = round(gross - entry_cost - exit_cost, 2)
        cash += exit_price * pos["qty"] - exit_cost
        notional = pos["entry_price"] * pos["qty"]
        trades.append(
            BacktestTrade(
                entry_ts=pos["entry_ts"],
                exit_ts=str(row.get("timestamp", "end")),
                side="BUY",
                symbol=symbol,
                entry_price=pos["entry_price"],
                exit_price=round(exit_price, 2),
                qty=pos["qty"],
                pnl=pnl,
                return_pct=round(pnl / notional * 100, 2) if notional else 0.0,
                stoploss=pos["stoploss"],
                target=0,
            )
        )
    positions.clear()

    final_capital = round(cash, 2)
    return _build_result(
        initial_capital,
        final_capital,
        equity_curve,
        trades,
        strategy_code,
        entry_meta["label"],
        max_open_positions=max_open_positions,
        symbols_traded=len(prepared),
        ai_entry=ai_entry,
        ai_exit=ai_exit,
    )


def run_swing_universe_backtest(
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
    max_open_positions: int = 5,
    universe: list[str] | None = None,
    top_n: int | None = 15,
    evaluation_days: int | None = 60,
    ai_entry: bool = False,
    ai_exit: bool = False,
) -> dict:
    from datetime import datetime, timedelta

    from trading_shared.strategies.swing_desk.stock_picker import default_universe, rank_universe

    end = datetime.fromisoformat(to_date)
    start = datetime.fromisoformat(from_date)
    load_from = start
    if (end - start).days < 420:
        load_from = end - timedelta(days=420)

    symbols = universe or default_universe()
    symbol_frames: dict[str, pd.DataFrame] = {}
    frame_list: list[tuple[str, pd.DataFrame]] = []
    data_source = "demo"

    for symbol in symbols:
        try:
            token, resolved = loader.resolve_token(symbol, None)
            df, source = loader.load(
                user_id=user_id,
                symbol=resolved,
                token=token,
                exchange=exchange,
                interval=interval or "1d",
                from_date=load_from.date().isoformat(),
                to_date=to_date,
                use_demo_data=use_demo_data,
            )
            if len(df) >= WARMUP_BARS:
                symbol_frames[resolved] = df
                frame_list.append((resolved, df))
                data_source = source
        except Exception:
            continue

    if not symbol_frames:
        raise ValueError("No symbols with sufficient daily history for swing backtest.")

    ranked = rank_universe(frame_list, strategy_code) if len(frame_list) > 1 else []
    if ranked and top_n:
        pick_symbols = {row["symbol"] for row in ranked[: max(1, min(top_n, len(ranked)))]}
        symbol_frames = {sym: df for sym, df in symbol_frames.items() if sym in pick_symbols}

    if not symbol_frames:
        raise ValueError("Could not rank any symbols for the selected swing strategy.")

    result = run_swing_portfolio_backtest(
        symbol_frames,
        strategy_code,
        initial_capital=initial_capital,
        risk_pct=risk_pct,
        max_open_positions=max_open_positions,
        ai_entry=ai_entry,
        ai_exit=ai_exit,
    )

    if evaluation_days and evaluation_days > 0:
        eval_start = (end - timedelta(days=evaluation_days)).date()
        filtered = _trades_in_window(result["trades"], eval_start, end.date())
        if filtered:
            result = _recompute_from_trades(
                result,
                filtered,
                initial_capital,
                strategy_code,
                result.get("strategy_label", strategy_code),
                max_open_positions,
                len(symbol_frames),
            )

    if ranked and top_n:
        pick_map = {row["symbol"]: row for row in ranked[:top_n]}
        enriched = []
        for row in result.get("picked_stocks") or []:
            meta = pick_map.get(row["symbol"], {})
            enriched.append({**row, **{k: v for k, v in meta.items() if k != "symbol"}})
        if not enriched:
            enriched = [
                {
                    "symbol": sym,
                    "score": pick_map.get(sym, {}).get("score"),
                    "screen_score": pick_map.get(sym, {}).get("screen_score"),
                    "preview_win_rate": pick_map.get(sym, {}).get("preview_win_rate"),
                    "total_trades": 0,
                    "win_rate": 0.0,
                    "total_pnl": 0.0,
                }
                for sym in symbol_frames
            ]
        result["picked_stocks"] = enriched

    result["data_source"] = data_source
    result["universe_screened"] = len(symbols)
    result["symbols_loaded"] = len(frame_list)
    result["symbols_traded"] = len(symbol_frames)
    result["top_n"] = len(symbol_frames)
    result["evaluation_days"] = evaluation_days
    result["selection_mode"] = "auto" if len(symbol_frames) > 1 else "single"
    return result


def _parse_trade_date(ts) -> object | None:
    if ts is None:
        return None
    try:
        return pd.to_datetime(ts, utc=True, format="mixed", errors="coerce").date()
    except Exception:
        return None


def _trades_in_window(trades: list[dict], start_date, end_date) -> list[dict]:
    filtered = []
    for trade in trades:
        exit_day = _parse_trade_date(trade.get("exit_ts"))
        if exit_day is None:
            continue
        if start_date <= exit_day <= end_date:
            filtered.append(trade)
    return filtered


def _recompute_from_trades(
    base: dict,
    trades: list[dict],
    initial_capital: float,
    strategy_code: str,
    strategy_label: str,
    max_open_positions: int,
    symbols_traded: int,
) -> dict:
    from trading_shared.backtest.types import BacktestTrade

    typed = [
        BacktestTrade(
            entry_ts=t["entry_ts"],
            exit_ts=t["exit_ts"],
            side=t["side"],
            symbol=t["symbol"],
            entry_price=t["entry_price"],
            exit_price=t["exit_price"],
            qty=t["qty"],
            pnl=t["pnl"],
            return_pct=t["return_pct"],
            stoploss=t.get("stoploss", 0),
            target=t.get("target", 0),
        )
        for t in trades
    ]
    total_pnl = round(sum(t.pnl for t in typed), 2)
    equity_curve = [initial_capital]
    running = initial_capital
    for t in sorted(typed, key=lambda x: str(x.exit_ts)):
        running += t.pnl
        equity_curve.append(round(running, 2))
    rebuilt = _build_result(
        initial_capital,
        round(initial_capital + total_pnl, 2),
        equity_curve,
        typed,
        strategy_code,
        strategy_label,
        max_open_positions=max_open_positions,
        symbols_traded=symbols_traded,
    )
    rebuilt["picked_stocks"] = base.get("picked_stocks")
    return rebuilt


def _build_result(
    initial_capital: float,
    capital: float,
    equity_curve: list[float],
    trades: list[BacktestTrade],
    strategy_code: str,
    strategy_label: str,
    *,
    max_open_positions: int,
    symbols_traded: int,
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
    per_symbol: dict[str, dict] = defaultdict(lambda: {"total_trades": 0, "total_pnl": 0.0, "wins": 0})
    for trade in trades:
        row = per_symbol[trade.symbol]
        row["total_trades"] += 1
        row["total_pnl"] = round(row["total_pnl"] + trade.pnl, 2)
        if trade.pnl > 0:
            row["wins"] += 1

    stock_summary = []
    for sym, row in sorted(per_symbol.items(), key=lambda item: item[1]["total_pnl"], reverse=True):
        tt = row["total_trades"]
        stock_summary.append(
            {
                "symbol": sym,
                "total_trades": tt,
                "win_rate": round(row["wins"] / tt * 100, 2) if tt else 0.0,
                "total_pnl": row["total_pnl"],
            }
        )

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
        "cost_model": "0.03% brokerage + 0.02% slippage per leg + 0.1% STT on sell",
        "max_open_positions": max_open_positions,
        "symbols_traded": symbols_traded,
        "picked_stocks": stock_summary[:20],
        "ai_entry": ai_entry,
        "ai_exit": ai_exit,
    }
