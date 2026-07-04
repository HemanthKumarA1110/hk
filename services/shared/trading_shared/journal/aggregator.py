"""Unified trade journal from DB entries, paper orders, and desk state."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from trading_shared.models import BrokerOrder, TradeJournalEntry
from trading_shared.strategies.scalping_desk.service import list_all_desk_paper_trades


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _infer_engine_from_order(row: BrokerOrder) -> str:
    product = (row.product or "").upper()
    sym = (row.symbol or "").upper()
    if sym in ("NIFTY", "BANKNIFTY") or "NIFTY" in sym or "BANK" in sym:
        return "scalping"
    if product in ("CNC", "DELIVERY"):
        return "swing"
    return "intraday"


def _scalping_ai_score(trade: dict[str, Any]) -> float | None:
    ai = trade.get("ai") or {}
    indicators = trade.get("indicators") or {}
    for key in ("validation_score", "score", "confidence"):
        val = ai.get(key) or indicators.get(key) or trade.get(key)
        if val is not None:
            try:
                return round(float(val), 1)
            except (TypeError, ValueError):
                continue
    return None


class JournalAggregator:
    def __init__(self, db: Session, user_id: int | None = None):
        self.db = db
        self.user_id = user_id

    def list_trades(
        self,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        engine: str | None = None,
        status: str | None = None,
        profitable: bool | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        rows.extend(self._from_journal_entries())
        if self.user_id is not None:
            rows.extend(self._from_paper_orders())
            rows.extend(self._from_scalping_desk())

        rows = self._apply_filters(rows, from_date, to_date, engine, status, profitable)
        rows.sort(key=lambda r: r.get("entry_datetime") or "", reverse=True)
        trimmed = rows[: max(1, min(limit, 1000))]

        closed_with_pnl = [r for r in trimmed if r.get("pnl") is not None]
        wins = sum(1 for r in closed_with_pnl if float(r["pnl"]) > 0)
        total_pnl = round(sum(float(r.get("pnl") or 0) for r in closed_with_pnl), 2)
        win_rate = round(wins / len(closed_with_pnl) * 100, 1) if closed_with_pnl else 0.0

        return {
            "entries": trimmed,
            "count": len(trimmed),
            "summary": {
                "total_pnl": total_pnl,
                "win_rate": win_rate,
                "total_trades": len(trimmed),
            },
            "filters": {
                "from_date": from_date.isoformat() if from_date else None,
                "to_date": to_date.isoformat() if to_date else None,
                "engine": engine,
                "status": status,
                "profitable": profitable,
            },
        }

    def _from_journal_entries(self) -> list[dict[str, Any]]:
        rows = (
            self.db.query(TradeJournalEntry)
            .order_by(TradeJournalEntry.created_at.desc())
            .limit(500)
            .all()
        )
        out: list[dict[str, Any]] = []
        for entry in rows:
            meta: dict[str, Any] = {}
            try:
                meta = json.loads(entry.metadata_json or "{}")
            except json.JSONDecodeError:
                pass
            out.append(
                {
                    "id": f"journal:{entry.id}",
                    "source": "journal",
                    "symbol": entry.symbol,
                    "engine": entry.engine,
                    "side": entry.side,
                    "qty": entry.qty,
                    "lots": meta.get("lots"),
                    "pnl": entry.pnl,
                    "ai_score": entry.ai_score,
                    "status": entry.status,
                    "entry_datetime": entry.created_at.isoformat() if entry.created_at else None,
                    "exit_datetime": entry.closed_at.isoformat() if entry.closed_at else None,
                }
            )
        return out

    def _from_paper_orders(self) -> list[dict[str, Any]]:
        assert self.user_id is not None
        rows = (
            self.db.query(BrokerOrder)
            .filter(
                BrokerOrder.user_id == self.user_id,
                BrokerOrder.execution_mode == "paper",
            )
            .order_by(BrokerOrder.created_at.desc())
            .limit(300)
            .all()
        )
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "id": f"paper:{row.id}",
                    "source": "live_trading",
                    "symbol": row.symbol,
                    "engine": _infer_engine_from_order(row),
                    "side": row.side,
                    "qty": row.qty,
                    "lots": None,
                    "pnl": None,
                    "ai_score": None,
                    "status": row.status,
                    "entry_datetime": row.created_at.isoformat() if row.created_at else None,
                    "exit_datetime": row.updated_at.isoformat()
                    if row.status == "filled" and row.updated_at
                    else None,
                }
            )
        return out

    def _from_scalping_desk(self) -> list[dict[str, Any]]:
        assert self.user_id is not None
        data = list_all_desk_paper_trades(self.db, self.user_id, limit=200)
        out: list[dict[str, Any]] = []
        for trade in data.get("trades") or []:
            lots = trade.get("qty")
            out.append(
                {
                    "id": f"scalping:{trade.get('order_id') or trade.get('symbol')}-{trade.get('timestamp')}",
                    "source": "scalping_desk",
                    "symbol": trade.get("symbol") or "—",
                    "engine": "scalping",
                    "side": trade.get("side") or trade.get("direction") or "—",
                    "qty": lots,
                    "lots": lots,
                    "pnl": trade.get("pnl"),
                    "ai_score": _scalping_ai_score(trade),
                    "status": trade.get("status") or "closed",
                    "entry_datetime": trade.get("entry_datetime") or trade.get("timestamp"),
                    "exit_datetime": trade.get("exit_datetime") or trade.get("exit_time"),
                }
            )
        return out

    @staticmethod
    def _apply_filters(
        rows: list[dict[str, Any]],
        from_date: date | None,
        to_date: date | None,
        engine: str | None,
        status: str | None,
        profitable: bool | None,
    ) -> list[dict[str, Any]]:
        engine_key = (engine or "").strip().lower()
        status_key = (status or "").strip().lower()

        filtered: list[dict[str, Any]] = []
        for row in rows:
            entry_dt = _parse_dt(row.get("entry_datetime"))
            if from_date or to_date:
                if entry_dt is None:
                    continue
                entry_day = entry_dt.date()
                if from_date and entry_day < from_date:
                    continue
                if to_date and entry_day > to_date:
                    continue

            if engine_key and engine_key not in ("all", ""):
                if (row.get("engine") or "").lower() != engine_key:
                    continue

            if status_key and status_key not in ("all", ""):
                row_status = (row.get("status") or "").lower()
                if status_key == "open" and row_status not in ("open", "active"):
                    continue
                if status_key == "closed" and row_status not in ("closed", "filled"):
                    continue
                if status_key not in ("open", "closed") and row_status != status_key:
                    continue

            if profitable is not None:
                pnl = row.get("pnl")
                if pnl is None:
                    continue
                if profitable and float(pnl) <= 0:
                    continue
                if not profitable and float(pnl) > 0:
                    continue

            filtered.append(row)
        return filtered
