from pydantic import BaseModel, Field


class ConfirmationSchema(BaseModel):
    name: str
    passed: bool
    weight: float
    detail: str = ""


class StrategySignalSchema(BaseModel):
    engine: str
    strategy_name: str
    symbol: str
    token: str
    side: str
    entry: float
    stoploss: float
    targets: list[float]
    trailing_stop: float
    timeframe: str
    score: float
    confidence: float
    risk_reward: float
    confirmations: list[ConfirmationSchema] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class StrategyRunResponse(BaseModel):
    generated_at: str
    scalping: list[StrategySignalSchema] = Field(default_factory=list)
    intraday: list[StrategySignalSchema] = Field(default_factory=list)
    swing: list[StrategySignalSchema] = Field(default_factory=list)


class EngineSignalsResponse(BaseModel):
    generated_at: str | None
    source: str | None = None
    universe_size: int | None = None
    history_loaded: int | None = None
    scan_hits: int | None = None
    min_score: float | None = None
    signals: list[StrategySignalSchema] = Field(default_factory=list)
