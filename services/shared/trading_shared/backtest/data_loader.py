"""Load OHLCV series from Angel One, database cache, or synthetic demo data."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy.orm import Session

from trading_shared.broker.angel_one.schemas import CandleRequest
from trading_shared.broker.angel_one.session_manager import AngelOneSessionManager
from trading_shared.config import get_settings
from trading_shared.market.scrip_master import ScripMasterService
from trading_shared.models import MarketCandle

logger = logging.getLogger(__name__)

INTERVAL_MAP = {
    "1m": "ONE_MINUTE",
    "3m": "THREE_MINUTE",
    "5m": "FIVE_MINUTE",
    "15m": "FIFTEEN_MINUTE",
    "1d": "ONE_DAY",
}

DEFAULT_PRICES = {
    "NIFTY": 24000.0,
    "BANKNIFTY": 52000.0,
    "SBIN": 800.0,
    "RELIANCE": 2800.0,
}


class BacktestDataLoader:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    def resolve_token(self, symbol: str, token: str | None = None) -> tuple[str, str]:
        if token:
            return token, symbol
        import redis

        redis_client = redis.from_url(self.settings.REDIS_URL, decode_responses=True)
        scrip = ScripMasterService(redis_client)
        clean = symbol.upper().replace("-EQ", "")
        if clean in ("NIFTY", "BANKNIFTY"):
            inst = scrip.index_token(clean)
            if inst:
                return inst.token, inst.symbol
        for inst in scrip.nifty50_equities():
            if inst.symbol == symbol or inst.symbol.replace("-EQ", "") == clean:
                return inst.token, inst.symbol
        return "99926000" if clean == "NIFTY" else "1", symbol

    def load(
        self,
        user_id: int,
        symbol: str,
        token: str | None,
        exchange: str,
        interval: str,
        from_date: str,
        to_date: str,
        use_demo_data: bool = False,
    ) -> tuple[pd.DataFrame, str]:
        token, symbol = self.resolve_token(symbol, token)
        if use_demo_data:
            return self._generate_demo(symbol, interval, from_date, to_date), "demo"

        db_df = self._load_from_db(token, interval, from_date, to_date)
        if len(db_df) >= 30:
            return db_df, "database"

        try:
            angel_df = self._load_from_angel(user_id, exchange, token, interval, from_date, to_date)
            if len(angel_df) >= 30:
                return angel_df, "angel_one"
        except Exception:
            logger.exception("Angel One historical fetch failed for %s", symbol)

        return self._generate_demo(symbol, interval, from_date, to_date), "demo"

    def _load_from_db(self, token: str, interval: str, from_date: str, to_date: str) -> pd.DataFrame:
        start = datetime.fromisoformat(from_date)
        end = datetime.fromisoformat(to_date) + timedelta(days=1)
        rows = (
            self.db.query(MarketCandle)
            .filter(
                MarketCandle.token == token,
                MarketCandle.interval == interval,
                MarketCandle.candle_ts >= start,
                MarketCandle.candle_ts <= end,
            )
            .order_by(MarketCandle.candle_ts.asc())
            .all()
        )
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(
            [
                {
                    "timestamp": r.candle_ts,
                    "open": r.open,
                    "high": r.high,
                    "low": r.low,
                    "close": r.close,
                    "volume": r.volume,
                }
                for r in rows
            ]
        )

    def _load_from_angel(
        self,
        user_id: int,
        exchange: str,
        token: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> pd.DataFrame:
        import redis

        redis_client = redis.from_url(self.settings.REDIS_URL, decode_responses=True)
        manager = AngelOneSessionManager(self.db, redis_client)

        async def fetch() -> dict:
            client = await manager.get_client_for_user(user_id)
            return await client.get_candles(
                CandleRequest(
                    exchange=exchange,
                    symboltoken=token,
                    interval=INTERVAL_MAP.get(interval, "FIVE_MINUTE"),
                    fromdate=f"{from_date} 09:15",
                    todate=f"{to_date} 15:30",
                )
            )

        response = asyncio.run(fetch())
        candles = response.get("data") or []
        if not candles:
            return pd.DataFrame()

        records = []
        for row in candles:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                continue
            records.append(
                {
                    "timestamp": pd.to_datetime(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                }
            )
        return pd.DataFrame(records)

    def _generate_demo(self, symbol: str, interval: str, from_date: str, to_date: str) -> pd.DataFrame:
        start = datetime.fromisoformat(from_date)
        end = datetime.fromisoformat(to_date)
        step = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "1d": 1440}.get(interval, 5)
        if interval == "1d":
            timestamps = pd.date_range(start=start, end=end, freq="B")
        else:
            timestamps = []
            current = start.replace(hour=9, minute=15)
            end_dt = end.replace(hour=15, minute=30)
            while current <= end_dt:
                if current.weekday() < 5 and 9 <= current.hour < 16:
                    timestamps.append(current)
                current += timedelta(minutes=step)

        clean = symbol.upper().replace("-EQ", "").split("-")[0]
        price = DEFAULT_PRICES.get(clean, 1000.0)
        rows = []
        for i, ts in enumerate(timestamps):
            drift = 1 + ((i % 11) - 5) * 0.0015
            close = max(price * drift, 1)
            high = close * 1.002
            low = close * 0.998
            open_px = close * 0.9995
            rows.append(
                {
                    "timestamp": ts,
                    "open": round(open_px, 2),
                    "high": round(high, 2),
                    "low": round(low, 2),
                    "close": round(close, 2),
                    "volume": 10000 + (i % 5000),
                }
            )
            price = close
        return pd.DataFrame(rows)
