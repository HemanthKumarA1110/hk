"""Trade journal analysis for AI insights."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from trading_shared.models import TradeJournalEntry


class JournalAnalyzer:
    def __init__(self, db: Session):
        self.db = db

    def analyze(self, limit: int = 200) -> dict[str, Any]:
        entries = (
            self.db.query(TradeJournalEntry)
            .order_by(TradeJournalEntry.created_at.desc())
            .limit(limit)
            .all()
        )
        if not entries:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "avg_pnl": 0,
                "best_engine": None,
                "worst_engine": None,
                "insights": ["No journal entries yet. Record trades to enable adaptive learning."],
            }

        wins = [e for e in entries if (e.pnl or 0) > 0]
        total_pnl = sum(e.pnl or 0 for e in entries)
        engine_pnl: dict[str, float] = {}
        engine_counts: Counter = Counter()

        for entry in entries:
            engine_counts[entry.engine] += 1
            engine_pnl[entry.engine] = engine_pnl.get(entry.engine, 0) + (entry.pnl or 0)

        best_engine = max(engine_pnl, key=engine_pnl.get) if engine_pnl else None
        worst_engine = min(engine_pnl, key=engine_pnl.get) if engine_pnl else None

        insights = [
            f"Win rate {len(wins)/len(entries)*100:.1f}% over {len(entries)} trades.",
            f"Total P&L: ₹{total_pnl:,.2f}.",
        ]
        if best_engine:
            insights.append(f"Best performing engine: {best_engine} (₹{engine_pnl[best_engine]:,.2f}).")
        if worst_engine and worst_engine != best_engine:
            insights.append(f"Underperforming engine: {worst_engine} — AI weights adjusted down.")

        mistake_tags = Counter()
        for entry in entries:
            if (entry.pnl or 0) >= 0:
                continue
            try:
                meta = json.loads(entry.metadata_json or "{}")
            except json.JSONDecodeError:
                meta = {}
            tag = meta.get("mistake", "unknown")
            mistake_tags[tag] += 1
        if mistake_tags:
            top_mistake = mistake_tags.most_common(1)[0][0]
            insights.append(f"Most common losing pattern: {top_mistake}.")

        return {
            "total_trades": len(entries),
            "win_rate": round(len(wins) / len(entries), 4),
            "avg_pnl": round(total_pnl / len(entries), 2),
            "total_pnl": round(total_pnl, 2),
            "best_engine": best_engine,
            "worst_engine": worst_engine,
            "engine_breakdown": {k: round(v, 2) for k, v in engine_pnl.items()},
            "insights": insights,
        }
