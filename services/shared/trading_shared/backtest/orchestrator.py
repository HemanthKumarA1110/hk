"""Backtest job orchestration with DB persistence."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from trading_shared.backtest.data_loader import BacktestDataLoader
from trading_shared.backtest.simulator import BacktestSimulator
from trading_shared.models.backtest import BacktestRun, BacktestTradeRecord
from trading_shared.schemas.backtest import BacktestRunRequest
from trading_shared.strategies.equity_strategy_catalog import confirmation_filter_for_code
from trading_shared.strategies.strategy_code_validation import validate_strategy_code_for_engine

logger = logging.getLogger(__name__)


class BacktestOrchestrator:
    def __init__(self, db: Session):
        self.db = db

    def create_run(self, user_id: int, payload: BacktestRunRequest) -> tuple[BacktestRun, bool]:
        validate_strategy_code_for_engine(payload.engine, payload.strategy_code)
        loader = BacktestDataLoader(self.db)
        if payload.engine in ("intraday", "swing") and payload.auto_pick_universe:
            token, symbol = "0", "AUTO-PICK"
        else:
            token, symbol = loader.resolve_token(payload.symbol, payload.token)
        config_json = payload.model_dump_json()
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
        existing = (
            self.db.query(BacktestRun)
            .filter(BacktestRun.user_id == user_id)
            .filter(BacktestRun.engine == payload.engine)
            .filter(BacktestRun.symbol == symbol)
            .filter(BacktestRun.token == token)
            .filter(BacktestRun.exchange == payload.exchange)
            .filter(BacktestRun.interval == payload.interval)
            .filter(BacktestRun.from_date == payload.from_date)
            .filter(BacktestRun.to_date == payload.to_date)
            .filter(BacktestRun.config_json == config_json)
            .filter(BacktestRun.status.in_(("pending", "running")))
            .filter(BacktestRun.created_at >= recent_cutoff)
            .order_by(BacktestRun.created_at.desc())
            .first()
        )
        if existing:
            return existing, False
        run = BacktestRun(
            user_id=user_id,
            engine=payload.engine,
            symbol=symbol,
            token=token,
            exchange=payload.exchange,
            interval=payload.interval,
            from_date=payload.from_date,
            to_date=payload.to_date,
            status="pending",
            config_json=config_json,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run, True

    def execute_run(self, run_id: int) -> dict:
        run = self.db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
        if not run:
            raise ValueError(f"Backtest run {run_id} not found")

        run.status = "running"
        self.db.commit()

        try:
            payload = BacktestRunRequest(**json.loads(run.config_json))
            validate_strategy_code_for_engine(run.engine, payload.strategy_code)
            loader = BacktestDataLoader(self.db)

            if run.engine == "intraday" and payload.auto_pick_universe:
                from trading_shared.strategies.intraday_desk.backtest import run_intraday_universe_backtest

                strategy_code = payload.strategy_code or "INTRA-ORB"
                result = run_intraday_universe_backtest(
                    loader,
                    user_id=run.user_id,
                    strategy_code=strategy_code,
                    exchange=run.exchange,
                    interval=run.interval,
                    from_date=run.from_date,
                    to_date=run.to_date,
                    use_demo_data=payload.use_demo_data,
                    initial_capital=payload.initial_capital,
                    risk_pct=payload.risk_pct,
                    top_n=payload.top_n,
                    ai_entry=payload.ai_entry,
                    ai_exit=payload.ai_exit,
                )
                run.data_source = result.get("data_source", "demo")
            elif run.engine == "intraday":
                df, source = loader.load(
                    user_id=run.user_id,
                    symbol=run.symbol,
                    token=run.token,
                    exchange=run.exchange,
                    interval=run.interval,
                    from_date=run.from_date,
                    to_date=run.to_date,
                    use_demo_data=payload.use_demo_data,
                )
                run.data_source = source

                from trading_shared.strategies.intraday_desk.backtest import run_intraday_strategy_backtest

                strategy_code = payload.strategy_code or "INTRA-ORB"
                result = run_intraday_strategy_backtest(
                    df=df,
                    strategy_code=strategy_code,
                    symbol=run.symbol,
                    initial_capital=payload.initial_capital,
                    risk_pct=payload.risk_pct,
                    ai_entry=payload.ai_entry,
                    ai_exit=payload.ai_exit,
                )
            elif run.engine == "swing":
                from trading_shared.strategies.swing_desk.backtest import run_swing_universe_backtest

                strategy_code = payload.strategy_code or "SWING-EMA"
                universe = None
                if not payload.auto_pick_universe and run.symbol and run.symbol != "AUTO-PICK":
                    universe = [run.symbol]
                result = run_swing_universe_backtest(
                    loader,
                    user_id=run.user_id,
                    strategy_code=strategy_code,
                    exchange=run.exchange,
                    interval=run.interval or "1d",
                    from_date=run.from_date,
                    to_date=run.to_date,
                    use_demo_data=payload.use_demo_data,
                    initial_capital=payload.initial_capital,
                    risk_pct=payload.risk_pct,
                    max_open_positions=payload.max_open_positions,
                    universe=universe,
                    top_n=payload.top_n or 15,
                    evaluation_days=60,
                    ai_entry=payload.ai_entry,
                    ai_exit=payload.ai_exit,
                )
                run.data_source = result.get("data_source", "demo")
            else:
                df, source = loader.load(
                    user_id=run.user_id,
                    symbol=run.symbol,
                    token=run.token,
                    exchange=run.exchange,
                    interval=run.interval,
                    from_date=run.from_date,
                    to_date=run.to_date,
                    use_demo_data=payload.use_demo_data,
                )
                run.data_source = source
                simulator = BacktestSimulator(
                    initial_capital=payload.initial_capital,
                    risk_pct=payload.risk_pct,
                )
                result = simulator.run(
                    df=df,
                    engine=run.engine,
                    symbol=run.symbol,
                    token=run.token,
                    max_loss_per_trade_pct=payload.max_loss_per_trade_pct,
                    max_daily_loss_pct=payload.max_daily_loss_pct,
                    max_trades_per_day=payload.max_trades_per_day,
                    confirmation_filter=confirmation_filter_for_code(payload.strategy_code),
                )

            run.metrics_json = json.dumps(
                {
                    "initial_capital": result["initial_capital"],
                    "final_capital": result["final_capital"],
                    "total_trades": result["total_trades"],
                    "win_rate": result["win_rate"],
                    "max_drawdown": result["max_drawdown"],
                    "profit_factor": result["profit_factor"],
                    "total_pnl": result["total_pnl"],
                    "avg_trade_pnl": result["avg_trade_pnl"],
                    "picked_stocks": result.get("picked_stocks"),
                    "universe_screened": result.get("universe_screened"),
                    "top_n": result.get("top_n"),
                    "evaluation_days": result.get("evaluation_days"),
                    "selection_mode": result.get("selection_mode"),
                    "max_open_positions": result.get("max_open_positions"),
                    "symbols_traded": result.get("symbols_traded"),
                    "ai_entry": payload.ai_entry,
                    "ai_exit": payload.ai_exit,
                }
            )
            run.equity_curve_json = json.dumps(result["equity_curve"])
            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)

            self.db.query(BacktestTradeRecord).filter(BacktestTradeRecord.run_id == run.id).delete()
            for trade in result["trades"]:
                self.db.add(
                    BacktestTradeRecord(
                        run_id=run.id,
                        entry_ts=trade["entry_ts"],
                        exit_ts=trade["exit_ts"],
                        side=trade["side"],
                        symbol=trade["symbol"],
                        entry_price=trade["entry_price"],
                        exit_price=trade["exit_price"],
                        qty=trade["qty"],
                        pnl=trade["pnl"],
                        return_pct=trade["return_pct"],
                        stoploss=trade["stoploss"],
                        target=trade["target"],
                    )
                )
            self.db.commit()
            return self.serialize_run(run)
        except Exception as exc:
            logger.exception("Backtest run %s failed", run_id)
            run.status = "failed"
            run.error_message = str(exc)
            run.completed_at = datetime.now(timezone.utc)
            self.db.commit()
            raise

    def get_run(self, run_id: int, user_id: int | None = None) -> BacktestRun | None:
        query = self.db.query(BacktestRun).filter(BacktestRun.id == run_id)
        if user_id is not None:
            query = query.filter(BacktestRun.user_id == user_id)
        return query.first()

    def list_runs(self, user_id: int, limit: int = 20) -> list[BacktestRun]:
        return self.list_runs_filtered(user_id, limit=limit)

    def list_runs_filtered(
        self,
        user_id: int,
        *,
        run_from: date | None = None,
        run_to: date | None = None,
        engine: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[BacktestRun]:
        query = self.db.query(BacktestRun).filter(BacktestRun.user_id == user_id)
        if run_from:
            start = datetime.combine(run_from, time.min, tzinfo=timezone.utc)
            query = query.filter(BacktestRun.created_at >= start)
        if run_to:
            end = datetime.combine(run_to, time.max, tzinfo=timezone.utc)
            query = query.filter(BacktestRun.created_at <= end)
        if engine and engine not in ("all", ""):
            query = query.filter(BacktestRun.engine == engine)
        if status and status not in ("all", ""):
            query = query.filter(BacktestRun.status == status)
        return query.order_by(BacktestRun.created_at.desc()).limit(max(1, min(limit, 2000))).all()

    def delete_runs_filtered(
        self,
        user_id: int,
        *,
        run_from: date | None = None,
        run_to: date | None = None,
        engine: str | None = None,
        status: str | None = None,
        delete_all: bool = False,
    ) -> int:
        query = self.db.query(BacktestRun).filter(BacktestRun.user_id == user_id)
        if not delete_all:
            if run_from:
                start = datetime.combine(run_from, time.min, tzinfo=timezone.utc)
                query = query.filter(BacktestRun.created_at >= start)
            if run_to:
                end = datetime.combine(run_to, time.max, tzinfo=timezone.utc)
                query = query.filter(BacktestRun.created_at <= end)
            if engine and engine not in ("all", ""):
                query = query.filter(BacktestRun.engine == engine)
            if status and status not in ("all", ""):
                query = query.filter(BacktestRun.status == status)
        runs = query.all()
        deleted = len(runs)
        for run in runs:
            self.db.delete(run)
        self.db.commit()
        return deleted

    def save_scalping_backtest_result(
        self,
        user_id: int,
        instrument_key: str,
        payload: dict[str, Any],
        result: dict[str, Any],
    ) -> BacktestRun | None:
        """Persist completed scalping desk backtest for the results archive."""
        try:
            from trading_shared.strategies.scalping_desk.constants import INSTRUMENTS

            meta = INSTRUMENTS.get(instrument_key, {})
            symbol = meta.get("underlying") or instrument_key.upper()
            strategy_code = payload.get("strategy_code") or result.get("strategy_code")
            from_day = str(payload.get("from_date") or result.get("from_date") or "")[:10]
            to_day = str(payload.get("to_date") or result.get("to_date") or "")[:10]
            if not from_day or not to_day:
                return None

            config = {
                "engine": "scalping",
                "instrument_key": instrument_key,
                "strategy_code": strategy_code,
                "timeframe": payload.get("timeframe", "1m"),
                "from_date": from_day,
                "to_date": to_day,
                "ai_entry": bool(payload.get("ai_entry") or result.get("ai_entry")),
                "ai_exit": bool(payload.get("ai_exit") or result.get("ai_exit")),
            }
            capital = float(result.get("initial_capital") or 100_000)
            total_pnl = float(result.get("total_pnl") or 0)
            total_trades = int(result.get("total_trades") or 0)
            metrics = {
                "initial_capital": capital,
                "final_capital": round(capital + total_pnl, 2),
                "total_trades": total_trades,
                "win_rate": float(result.get("win_rate") or 0),
                "max_drawdown": float(result.get("max_drawdown_pct") or result.get("max_drawdown") or 0),
                "profit_factor": float(result.get("profit_factor") or 0),
                "total_pnl": round(total_pnl, 2),
                "avg_trade_pnl": round(total_pnl / max(total_trades, 1), 2),
                "strategy_code": strategy_code,
                "strategy_label": result.get("strategy_label"),
                "ai_entry": config["ai_entry"],
                "ai_exit": config["ai_exit"],
            }
            equity = result.get("equity_curve") or []
            if equity and isinstance(equity[0], dict):
                equity = [float(p.get("equity", 0)) for p in equity]

            run = BacktestRun(
                user_id=user_id,
                engine="scalping",
                symbol=symbol,
                token="0",
                exchange="NSE",
                interval=str(payload.get("timeframe") or "1m"),
                from_date=from_day,
                to_date=to_day,
                status="completed" if str(result.get("status", "completed")) != "failed" else "failed",
                data_source=str(result.get("data_source") or ("demo" if result.get("warning") else "angel_one")),
                config_json=json.dumps(config),
                metrics_json=json.dumps(metrics),
                equity_curve_json=json.dumps(equity[:500]),
                error_message=result.get("message") if total_trades == 0 and result.get("message") else None,
                completed_at=datetime.now(timezone.utc),
            )
            self.db.add(run)
            self.db.commit()
            self.db.refresh(run)
            return run
        except Exception:
            logger.exception("Failed to persist scalping backtest result for %s", instrument_key)
            self.db.rollback()
            return None

    @staticmethod
    def _parse_config(run: BacktestRun) -> dict[str, Any]:
        try:
            return json.loads(run.config_json or "{}")
        except json.JSONDecodeError:
            return {}

    @classmethod
    def serialize_run_summary(cls, run: BacktestRun) -> dict[str, Any]:
        metrics = json.loads(run.metrics_json or "{}")
        config = cls._parse_config(run)
        return {
            "run_id": run.id,
            "status": run.status,
            "engine": run.engine,
            "strategy_code": config.get("strategy_code") or metrics.get("strategy_code"),
            "strategy_label": metrics.get("strategy_label"),
            "symbol": run.symbol,
            "instrument_key": config.get("instrument_key"),
            "interval": run.interval,
            "from_date": run.from_date,
            "to_date": run.to_date,
            "data_source": run.data_source,
            "ai_entry": bool(config.get("ai_entry") or metrics.get("ai_entry")),
            "ai_exit": bool(config.get("ai_exit") or metrics.get("ai_exit")),
            "total_trades": metrics.get("total_trades"),
            "win_rate": metrics.get("win_rate"),
            "total_pnl": metrics.get("total_pnl"),
            "max_drawdown": metrics.get("max_drawdown"),
            "profit_factor": metrics.get("profit_factor"),
            "final_capital": metrics.get("final_capital"),
            "initial_capital": metrics.get("initial_capital"),
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }

    @staticmethod
    def serialize_run(run: BacktestRun) -> dict:
        metrics = json.loads(run.metrics_json or "{}")
        trades = [
            {
                "entry_ts": t.entry_ts,
                "exit_ts": t.exit_ts,
                "side": t.side,
                "symbol": t.symbol,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "qty": t.qty,
                "pnl": t.pnl,
                "return_pct": t.return_pct,
                "stoploss": t.stoploss,
                "target": t.target,
            }
            for t in run.trades
        ]
        config = BacktestOrchestrator._parse_config(run)
        return {
            "run_id": run.id,
            "status": run.status,
            "engine": run.engine,
            "symbol": run.symbol,
            "interval": run.interval,
            "from_date": run.from_date,
            "to_date": run.to_date,
            "data_source": run.data_source,
            "strategy_code": config.get("strategy_code") or metrics.get("strategy_code"),
            "instrument_key": config.get("instrument_key"),
            "metrics": metrics if metrics else None,
            "equity_curve": json.loads(run.equity_curve_json or "[]"),
            "trades": trades,
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }
