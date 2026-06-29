from pydantic import BaseModel, Field


class AIDecisionSchema(BaseModel):
    symbol: str
    token: str
    engine: str
    action: str
    score: float
    threshold: float
    confidence: float
    regime: str
    reasoning: list[str] = Field(default_factory=list)
    features: dict = Field(default_factory=dict)
    signal: dict = Field(default_factory=dict)
    recommended_size_pct: float = 100.0


class AIRunResponse(BaseModel):
    generated_at: str
    decisions: list[AIDecisionSchema] = Field(default_factory=list)
    approved: list[AIDecisionSchema] = Field(default_factory=list)
    rejected_count: int = 0
    journal_insights: dict = Field(default_factory=dict)
    weights: dict = Field(default_factory=dict)


class JournalEntryRequest(BaseModel):
    symbol: str
    engine: str
    side: str
    entry_price: float
    exit_price: float | None = None
    current_price: float | None = None
    qty: int = 1
    pnl: float | None = None
    status: str = "closed"
    features: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    ai_score: float | None = None


class JournalInsightsResponse(BaseModel):
    total_trades: int
    win_rate: float
    avg_pnl: float
    total_pnl: float = 0
    best_engine: str | None = None
    worst_engine: str | None = None
    engine_breakdown: dict = Field(default_factory=dict)
    insights: list[str] = Field(default_factory=list)
