"""Continuous market scanner using live tick cache."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from trading_shared.market.analytics import detect_gap, relative_volume, sector_strength
from trading_shared.market.redis_bus import MarketRedisBus
from trading_shared.market.scrip_master import SECTOR_MAP, ScripMasterService
from trading_shared.models import MarketScanResult

logger = logging.getLogger(__name__)


class MarketScanner:
    def __init__(self, redis_bus: MarketRedisBus, scrip_service: ScripMasterService):
        self.redis_bus = redis_bus
        self.scrip_service = scrip_service
        self._volume_baselines: dict[str, float] = {}

    def run_scan(self, db: Session | None = None) -> dict[str, Any]:
        generated_at = datetime.now(timezone.utc).isoformat()
        hits: list[dict[str, Any]] = []
        sector_returns: dict[str, list[float]] = {}

        try:
            equities = self.scrip_service.nifty50_equities()
        except Exception as exc:
            logger.warning("Scanner skipped: scrip master unavailable (%s)", exc)
            payload = {"generated_at": generated_at, "hits": [], "sector_strength": {}, "error": str(exc)}
            self.redis_bus.store_scan_results(payload)
            return payload

        for instrument in equities:
            tick = self.redis_bus.get_tick(1, instrument.token)
            if not tick:
                continue

            ltp = tick.get("ltp", 0)
            open_price = tick.get("open", 0)
            prev_close = tick.get("close", 0) or open_price
            volume = tick.get("volume", 0)
            symbol = instrument.symbol

            baseline = self._volume_baselines.get(symbol, max(volume, 1))
            self._volume_baselines[symbol] = (baseline * 0.9) + (volume * 0.1)
            rel_vol = relative_volume(volume, baseline)
            if rel_vol >= 2:
                hits.append(
                    {
                        "scan_type": "relative_volume",
                        "symbol": symbol,
                        "token": instrument.token,
                        "score": min(rel_vol * 10, 100),
                        "details": {"relative_volume": rel_vol, "volume": volume},
                    }
                )

            gap = detect_gap(open_price, prev_close)
            if gap:
                hits.append(
                    {
                        "scan_type": gap["gap_type"],
                        "symbol": symbol,
                        "token": instrument.token,
                        "score": min(abs(gap["gap_pct"]) * 10, 100),
                        "details": gap,
                    }
                )

            if prev_close > 0:
                change_pct = ((ltp - prev_close) / prev_close) * 100
                sector = SECTOR_MAP.get(symbol, "Other")
                sector_returns.setdefault(sector, []).append(change_pct)
                if change_pct >= 1.5:
                    hits.append(
                        {
                            "scan_type": "momentum",
                            "symbol": symbol,
                            "token": instrument.token,
                            "score": min(change_pct * 8, 100),
                            "details": {"change_pct": round(change_pct, 2), "ltp": ltp},
                        }
                    )
                if ltp >= tick.get("high", ltp) * 0.998 and tick.get("high", 0) > 0:
                    hits.append(
                        {
                            "scan_type": "breakout",
                            "symbol": symbol,
                            "token": instrument.token,
                            "score": 75,
                            "details": {"day_high": tick.get("high"), "ltp": ltp},
                        }
                    )

        sector_scores = sector_strength(sector_returns)
        hits.sort(key=lambda item: item["score"], reverse=True)
        payload = {
            "generated_at": generated_at,
            "hits": hits[:50],
            "sector_strength": sector_scores,
        }
        self.redis_bus.store_scan_results(payload)
        self.redis_bus.store_sector_strength(sector_scores)

        if db:
            for hit in hits[:20]:
                db.add(
                    MarketScanResult(
                        scan_type=hit["scan_type"],
                        symbol=hit["symbol"],
                        token=hit["token"],
                        score=hit["score"],
                        payload=json.dumps(hit["details"]),
                    )
                )
            db.commit()

        return payload
