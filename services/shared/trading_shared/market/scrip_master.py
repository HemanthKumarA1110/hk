"""Download and query Angel One OpenAPI scrip master."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

import httpx
import pandas as pd
import redis

from trading_shared.market.constants import SCRIP_MASTER_URL

logger = logging.getLogger(__name__)

REDIS_SCRIP_KEY = "market:scrip_master"
REDIS_SCRIP_UPDATED_KEY = "market:scrip_master:updated_at"


def index_strike_step(underlying: str) -> int:
    return 100 if underlying == "BANKNIFTY" else 50


def normalize_scrip_strike(raw_strike: float, spot: float = 0) -> float:
    """Convert Angel scrip strike to index points (index options are stored ×100)."""
    if raw_strike <= 0:
        return raw_strike
    if spot > 0 and raw_strike > spot * 50:
        return raw_strike / 100.0
    if spot <= 0 and raw_strike >= 100_000:
        return raw_strike / 100.0
    return raw_strike


def parse_option_strike_symbol(symbol: str) -> float | None:
    """Parse strike from NFO index option symbol e.g. NIFTY07JUL2624250CE."""
    sym = str(symbol or "").upper().strip()
    if not sym or sym.endswith("FUT"):
        return None
    for suffix in ("CE", "PE"):
        if sym.endswith(suffix):
            sym = sym[:-2]
            break
    else:
        return None
    digits = "".join(ch for ch in sym if ch.isdigit())
    if len(digits) < 5:
        return None
    try:
        return float(digits[-5:])
    except ValueError:
        return None


@dataclass
class Instrument:
    token: str
    symbol: str
    name: str
    exchange: str
    instrument_type: str
    expiry: str
    strike: float
    lot_size: int

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Instrument":
        return cls(
            token=str(row.get("token", "")),
            symbol=str(row.get("symbol", "")),
            name=str(row.get("name", "")),
            exchange=str(row.get("exch_seg", "")),
            instrument_type=str(row.get("instrumenttype", "")),
            expiry=str(row.get("expiry", "")),
            strike=float(row.get("strike", 0) or 0),
            lot_size=int(float(row.get("lotsize", 1) or 1)),
        )


class ScripMasterService:
    def __init__(self, redis_client: redis.Redis | None = None):
        self.redis = redis_client
        self._df: pd.DataFrame | None = None

    def _load_from_redis(self) -> bool:
        if self._df is not None:
            return True
        if not self.redis:
            return False
        cached = self.redis.get(REDIS_SCRIP_KEY)
        if not cached:
            return False
        records = json.loads(cached)
        self._df = pd.DataFrame(records)
        logger.debug("Scrip master loaded from Redis cache (%s instruments)", len(records))
        return True

    def ensure_loaded(self) -> bool:
        return self._load_from_redis()

    async def refresh(self, force: bool = False) -> pd.DataFrame:
        if not force and self._load_from_redis():
            return self._df

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.get(SCRIP_MASTER_URL)
            response.raise_for_status()
            records = response.json()

        self._df = pd.DataFrame(records)
        if self.redis:
            self.redis.setex(REDIS_SCRIP_KEY, 86400, json.dumps(records))
            self.redis.set(REDIS_SCRIP_UPDATED_KEY, datetime.now(timezone.utc).isoformat())
        logger.info("Scrip master refreshed with %s instruments", len(records))
        return self._df

    def dataframe(self) -> pd.DataFrame:
        if self._df is None and not self._load_from_redis():
            raise RuntimeError("Scrip master not loaded. Call refresh() first.")
        return self._df

    def get_by_token(self, token: str) -> Instrument | None:
        df = self.dataframe()
        match = df[df["token"].astype(str) == str(token)]
        if match.empty:
            return None
        return Instrument.from_row(match.iloc[0].to_dict())

    def get_equity_by_symbol(self, symbol: str, exchange: str = "NSE") -> Instrument | None:
        sym = symbol.upper().strip()
        if exchange == "NSE" and not sym.endswith("-EQ"):
            sym = f"{sym}-EQ"
        df = self.dataframe()
        match = df[
            (df["exch_seg"] == exchange)
            & (df["instrumenttype"] == "")
            & (df["symbol"] == sym)
        ]
        if match.empty:
            return None
        return Instrument.from_row(match.iloc[0].to_dict())

    def search_equity(self, query: str, exchange: str = "NSE", limit: int = 20) -> list[Instrument]:
        query = query.upper().strip().replace("-EQ", "")
        exact = self.get_equity_by_symbol(f"{query}-EQ", exchange=exchange)
        if exact:
            return [exact]

        df = self.dataframe()
        mask = (
            (df["exch_seg"] == exchange)
            & (df["instrumenttype"] == "")
            & (df["symbol"].str.endswith("-EQ", na=False))
            & (df["symbol"].str.contains(query, na=False))
        )
        rows = df[mask].head(limit)
        return [Instrument.from_row(row.to_dict()) for _, row in rows.iterrows()]

    def nifty50_equities(self) -> list[Instrument]:
        symbols = NIFTY50_SYMBOLS
        df = self.dataframe()
        mask = (df["exch_seg"] == "NSE") & (df["symbol"].isin(symbols))
        return [Instrument.from_row(row.to_dict()) for _, row in df[mask].iterrows()]

    def index_token(self, index_name: str) -> Instrument | None:
        from trading_shared.broker.angel_one.constants import INDEX_TOKENS

        mapping = {
            "NIFTY": ("NSE", "Nifty 50"),
            "BANKNIFTY": ("NSE", "Nifty Bank"),
        }
        if index_name not in mapping:
            return None

        try:
            exchange, name = mapping[index_name]
            df = self.dataframe()
            match = df[(df["exch_seg"] == exchange) & (df["name"] == name)]
            if not match.empty:
                return Instrument.from_row(match.iloc[0].to_dict())
        except RuntimeError:
            logger.warning("Scrip master unavailable for %s; using static index token fallback", index_name)

        fallback = INDEX_TOKENS.get(index_name)
        if not fallback:
            return None
        return Instrument(
            token=str(fallback["symboltoken"]),
            symbol=str(fallback["tradingsymbol"]),
            name=str(fallback["tradingsymbol"]),
            exchange=str(fallback["exchange"]),
            instrument_type="AMXIDX",
            expiry="",
            strike=0.0,
            lot_size=1,
        )

    def nearest_expiry_options(self, underlying: str, spot: float, strike_window: int = 10) -> list[Instrument]:
        df = self.dataframe()
        prefix = "NIFTY" if underlying == "NIFTY" else "BANKNIFTY"
        options = df[
            (df["exch_seg"] == "NFO")
            & (df["name"].str.startswith(prefix, na=False))
            & (df["instrumenttype"].isin(["OPTIDX"]))
        ].copy()
        if options.empty:
            return []

        options["expiry_dt"] = pd.to_datetime(options["expiry"], format="%d%b%Y", errors="coerce")
        nearest_expiry = options["expiry_dt"].min()
        chain = options[options["expiry_dt"] == nearest_expiry].copy()
        chain["strike"] = pd.to_numeric(chain["strike"], errors="coerce")
        chain["strike"] = chain["strike"].apply(lambda s: normalize_scrip_strike(float(s), spot))
        half_window = strike_window * index_strike_step(underlying)
        chain = chain[
            (chain["strike"] >= spot - half_window) & (chain["strike"] <= spot + half_window)
        ]
        instruments: list[Instrument] = []
        for _, row in chain.iterrows():
            payload = row.to_dict()
            payload["strike"] = normalize_scrip_strike(float(payload.get("strike") or 0), spot)
            instruments.append(Instrument.from_row(payload))
        return instruments

    def futures_chain(self, underlying: str, count: int = 2) -> list[Instrument]:
        df = self.dataframe()
        prefix = "NIFTY" if underlying == "NIFTY" else "BANKNIFTY"
        futures = df[
            (df["exch_seg"] == "NFO")
            & (df["name"].str.startswith(prefix, na=False))
            & (df["instrumenttype"] == "FUTIDX")
        ].copy()
        if futures.empty:
            return []
        futures["expiry_dt"] = pd.to_datetime(futures["expiry"], format="%d%b%Y", errors="coerce")
        futures = futures.sort_values("expiry_dt").head(count)
        return [Instrument.from_row(row.to_dict()) for _, row in futures.iterrows()]


NIFTY50_SYMBOLS = [
    "RELIANCE-EQ", "TCS-EQ", "HDFCBANK-EQ", "INFY-EQ", "ICICIBANK-EQ",
    "HINDUNILVR-EQ", "ITC-EQ", "SBIN-EQ", "BHARTIARTL-EQ", "KOTAKBANK-EQ",
    "LT-EQ", "AXISBANK-EQ", "ASIANPAINT-EQ", "MARUTI-EQ", "TITAN-EQ",
    "SUNPHARMA-EQ", "BAJFINANCE-EQ", "WIPRO-EQ", "HCLTECH-EQ", "ULTRACEMCO-EQ",
    "NTPC-EQ", "POWERGRID-EQ", "M&M-EQ", "TATAMOTORS-EQ", "ADANIENT-EQ",
    "JSWSTEEL-EQ", "TATASTEEL-EQ", "INDUSINDBK-EQ", "GRASIM-EQ", "TECHM-EQ",
    "CIPLA-EQ", "DRREDDY-EQ", "EICHERMOT-EQ", "BPCL-EQ", "HEROMOTOCO-EQ",
    "DIVISLAB-EQ", "COALINDIA-EQ", "BAJAJFINSV-EQ", "APOLLOHOSP-EQ", "BRITANNIA-EQ",
    "HINDALCO-EQ", "SBILIFE-EQ", "TATACONSUM-EQ", "NESTLEIND-EQ", "ADANIPORTS-EQ",
    "ONGC-EQ", "LTIM-EQ", "HDFCLIFE-EQ", "UPL-EQ", "BAJAJ-AUTO-EQ",
]

SECTOR_MAP = {
    "RELIANCE-EQ": "Energy", "ONGC-EQ": "Energy", "BPCL-EQ": "Energy",
    "TCS-EQ": "IT", "INFY-EQ": "IT", "HCLTECH-EQ": "IT", "WIPRO-EQ": "IT", "TECHM-EQ": "IT", "LTIM-EQ": "IT",
    "HDFCBANK-EQ": "Finance", "ICICIBANK-EQ": "Finance", "KOTAKBANK-EQ": "Finance", "AXISBANK-EQ": "Finance",
    "SBIN-EQ": "Finance", "INDUSINDBK-EQ": "Finance", "BAJFINANCE-EQ": "Finance", "BAJAJFINSV-EQ": "Finance",
    "HDFCLIFE-EQ": "Finance", "SBILIFE-EQ": "Finance",
    "HINDUNILVR-EQ": "FMCG", "ITC-EQ": "FMCG", "NESTLEIND-EQ": "FMCG", "BRITANNIA-EQ": "FMCG", "TATACONSUM-EQ": "FMCG",
    "SUNPHARMA-EQ": "Pharma", "CIPLA-EQ": "Pharma", "DRREDDY-EQ": "Pharma", "DIVISLAB-EQ": "Pharma",
    "MARUTI-EQ": "Auto", "TATAMOTORS-EQ": "Auto", "M&M-EQ": "Auto", "EICHERMOT-EQ": "Auto", "BAJAJ-AUTO-EQ": "Auto",
    "TATASTEEL-EQ": "Metal", "JSWSTEEL-EQ": "Metal", "HINDALCO-EQ": "Metal",
    "LT-EQ": "Infra", "ADANIPORTS-EQ": "Infra", "POWERGRID-EQ": "Infra", "NTPC-EQ": "Infra",
}
