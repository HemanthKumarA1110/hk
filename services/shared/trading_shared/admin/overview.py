"""Admin dashboard aggregation from Redis + PostgreSQL."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import redis
from sqlalchemy.orm import Session

from trading_shared.ai.constants import REDIS_AI_DECISIONS_KEY
from trading_shared.ai.journal_analyzer import JournalAnalyzer
from trading_shared.ai.orchestrator import AIOrchestrator
from trading_shared.config import get_settings
from trading_shared.market.redis_bus import MarketRedisBus
from trading_shared.models import TradeJournalEntry
from trading_shared.risk.manager import RiskManager
from trading_shared.strategies.orchestrator import StrategyOrchestrator


class AdminOverviewAggregator:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.redis = redis.from_url(self.settings.REDIS_URL, decode_responses=True)
        self.market_bus = MarketRedisBus(self.settings.REDIS_URL)
        self.risk = RiskManager(self.settings.REDIS_URL)

    def overview(self) -> dict:
        journal = JournalAnalyzer(self.db).analyze()
        ai_cached = AIOrchestrator.get_cached()
        risk = self.risk.status()
        stream = self.market_bus.get_stream_status() or {}
        scan = self.market_bus.get_scan_results() or {}

        scalping = StrategyOrchestrator.get_cached("scalping")
        intraday = StrategyOrchestrator.get_cached("intraday")
        swing = StrategyOrchestrator.get_cached("swing")

        open_trades = (
            self.db.query(TradeJournalEntry)
            .filter(TradeJournalEntry.status.in_(["open", "active"]))
            .order_by(TradeJournalEntry.created_at.desc())
            .limit(20)
            .all()
        )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_pnl": journal.get("total_pnl", 0),
                "win_rate": journal.get("win_rate", 0),
                "total_trades": journal.get("total_trades", 0),
                "ai_approved": len(ai_cached.get("approved", [])),
                "ai_rejected": ai_cached.get("rejected_count", 0),
                "signal_counts": {
                    "scalping": len(scalping.get("signals", [])),
                    "intraday": len(intraday.get("signals", [])),
                    "swing": len(swing.get("signals", [])),
                },
                "risk_status": risk.get("status"),
                "can_trade": risk.get("can_trade"),
                "stream_connected": stream.get("connected", False),
                "scan_universe_size": len(scan.get("hits", [])),
            },
            "risk_meter": risk,
            "journal_insights": journal,
            "ai_decisions": ai_cached.get("approved", [])[:5],
            "open_trades": [self._serialize_trade(t) for t in open_trades],
            "stream_status": stream,
        }

    def equity_curve(self) -> dict:
        entries = (
            self.db.query(TradeJournalEntry)
            .filter(TradeJournalEntry.status == "closed")
            .order_by(TradeJournalEntry.created_at.asc())
            .all()
        )
        base_equity = self.risk.engine.state.equity
        cumulative = 0.0
        points = [{"date": datetime.now(timezone.utc).date().isoformat(), "equity": base_equity, "pnl": 0}]
        for entry in entries:
            cumulative += entry.pnl or 0
            points.append(
                {
                    "date": entry.created_at.date().isoformat() if entry.created_at else "",
                    "equity": round(base_equity + cumulative, 2),
                    "pnl": round(entry.pnl or 0, 2),
                    "symbol": entry.symbol,
                    "engine": entry.engine,
                }
            )
        return {"points": points, "current_equity": round(base_equity + cumulative, 2)}

    def journal_entries(self, limit: int = 50) -> dict:
        rows = (
            self.db.query(TradeJournalEntry)
            .order_by(TradeJournalEntry.created_at.desc())
            .limit(limit)
            .all()
        )
        return {"entries": [self._serialize_trade(r) for r in rows]}

    def backtest_preview(self) -> dict:
        return {
            "status": "ready",
            "message": "Production backtesting engine with scalping, intraday, and swing replay.",
            "supported_engines": ["scalping", "intraday", "swing"],
            "supported_intervals": ["1m", "3m", "5m", "15m", "1d"],
            "default_capital": self.risk.engine.state.equity,
        }

    @staticmethod
    def _serialize_trade(entry: TradeJournalEntry) -> dict:
        return {
            "id": entry.id,
            "symbol": entry.symbol,
            "engine": entry.engine,
            "side": entry.side,
            "entry_price": entry.entry_price,
            "exit_price": entry.exit_price,
            "current_price": entry.current_price,
            "qty": entry.qty,
            "pnl": entry.pnl,
            "status": entry.status,
            "ai_score": entry.ai_score,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        }
