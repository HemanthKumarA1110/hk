"""Default and adaptive feature weights for AI scoring."""

DEFAULT_WEIGHTS: dict[str, float] = {
    "trend": 12.0,
    "volume": 10.0,
    "volatility": 8.0,
    "oi": 10.0,
    "greeks": 8.0,
    "sentiment": 7.0,
    "sector_strength": 8.0,
    "price_action": 12.0,
    "risk_reward": 15.0,
    "market_regime": 10.0,
}

REDIS_AI_DECISIONS_KEY = "ai:decisions:latest"
REDIS_AI_WEIGHTS_KEY = "ai:weights"
REDIS_AI_JOURNAL_INSIGHTS_KEY = "ai:journal:insights"
PUBSUB_AI_DECISIONS = "ai:decisions"

DEFAULT_ENTER_THRESHOLD = 75.0
DEFAULT_SCALE_IN_THRESHOLD = 65.0
DEFAULT_PARTIAL_BOOK_THRESHOLD = 55.0
DEFAULT_EXIT_THRESHOLD = 45.0
