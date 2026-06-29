"""Backtest job orchestration with DB persistence."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from trading_shared.backtest.data_loader import BacktestDataLoader
from trading_shared.backtest.simulator import BacktestSimulator
from trading_shared.models.backtest import BacktestRun, BacktestTradeRecord
from trading_shared.schemas.backtest import BacktestRunRequest

logger = logging.getLogger(__name__)


class BacktestOrchestrator:
    def __init__(self, db: Session):
        self.db = db

    def create_run(self, user_id: int, payload: BacktestRunRequest) -> BacktestRun:
        loader = BacktestDataLoader(self.db)
        token, symbol = loader.resolve_token(payload.symbol, payload.token)
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
            config_json=payload.model_dump_json(),
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def execute_run(self, run_id: int) -> dict:
        run = self.db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
        if not run:
            raise ValueError(f"Backtest run {run_id} not found")

        run.status = "running"
        self.db.commit()

        try:
            payload = BacktestRunRequest(**json.loads(run.config_json))
            loader = BacktestDataLoader(self.db)
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
        return (
            self.db.query(BacktestRun)
            .filter(BacktestRun.user_id == user_id)
            .order_by(BacktestRun.created_at.desc())
            .limit(limit)
            .all()
        )

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
        return {
            "run_id": run.id,
            "status": run.status,
            "engine": run.engine,
            "symbol": run.symbol,
            "interval": run.interval,
            "from_date": run.from_date,
            "to_date": run.to_date,
            "data_source": run.data_source,
            "metrics": metrics if metrics else None,
            "equity_curve": json.loads(run.equity_curve_json or "[]"),
            "trades": trades,
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }
