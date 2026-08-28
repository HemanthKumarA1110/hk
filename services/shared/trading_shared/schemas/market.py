from pydantic import BaseModel, Field


class TickSnapshot(BaseModel):
    token: str
    symbol: str | None = None
    exchange: str | None = None
    ltp: float
    open: float = 0
    high: float = 0
    low: float = 0
    close: float = 0
    volume: float = 0
    oi: float = 0
    vwap: float | None = None
    exchange_timestamp: int | None = None


class CandleSnapshot(BaseModel):
    token: str
    symbol: str
    interval: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    oi: float | None = None
    candle_ts: str


class ScanHit(BaseModel):
    scan_type: str
    symbol: str
    token: str
    score: float
    details: dict


class ScanResponse(BaseModel):
    generated_at: str
    hits: list[ScanHit] = Field(default_factory=list)
    sector_strength: dict[str, float] = Field(default_factory=dict)


class OptionChainRow(BaseModel):
    symbol: str
    token: str
    strike: float
    option_type: str
    ltp: float = 0
    oi: float = 0
    volume: float = 0
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None


class OptionChainResponse(BaseModel):
    underlying: str
    expiry: str
    spot: float
    pcr: float | None
    total_ce_oi: float
    total_pe_oi: float
    rows: list[OptionChainRow]


class StreamStatusResponse(BaseModel):
    connected: bool
    desired: bool = False
    enabled: bool = False
    subscriptions: int
    ticks_received: int
    last_tick_at: str | None = None
    scanner_running: bool
    scrip_master_updated_at: str | None = None
    message: str | None = None


class IndexQuote(BaseModel):
    name: str
    label: str
    symboltoken: str | None = None
    exchange: str | None = None
    ltp: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    source: str | None = None
    error: str | None = None


class IndexQuotesResponse(BaseModel):
    generated_at: str
    indices: list[IndexQuote]


class SymbolSearchHit(BaseModel):
    symbol: str
    token: str
    name: str
    exchange: str = "NSE"
    source: str | None = None


class SymbolSearchResponse(BaseModel):
    query: str
    results: list[SymbolSearchHit] = Field(default_factory=list)
