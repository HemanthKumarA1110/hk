import socket
import uuid
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def _default_mac() -> str:
    node = uuid.getnode()
    return ":".join(f"{(node >> elements) & 0xFF:02x}" for elements in range(40, -8, -8))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ENV: str = "development"
    SERVICE_NAME: str = "trading-service"

    DATABASE_URL: str = "postgresql://trader:traderpass@localhost:5432/trading"
    REDIS_URL: str = "redis://localhost:6379/0"

    JWT_SECRET: str = "change_me_in_production"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    ENCRYPTION_KEY: str = "change_me_32_byte_base64_fernet_key=="

    ANGEL_API_KEY: str = ""
    ANGEL_CLIENT_CODE: str = ""
    ANGEL_PASSWORD: str = ""
    ANGEL_TOTP_SECRET: str = ""

    ANGEL_CLIENT_LOCAL_IP: str = _default_local_ip()
    ANGEL_CLIENT_PUBLIC_IP: str = _default_local_ip()
    ANGEL_MAC_ADDRESS: str = _default_mac()

    AUTH_SERVICE_URL: str = "http://auth-service:8001"
    MARKET_DATA_SERVICE_URL: str = "http://market-data-service:8002"
    STRATEGY_ENGINE_URL: str = "http://strategy-engine:8003"
    AI_DECISION_ENGINE_URL: str = "http://ai-decision-engine:8004"
    RISK_MANAGER_URL: str = "http://risk-manager:8005"
    ORDER_EXECUTION_URL: str = "http://order-execution-engine:8006"
    BACKTESTING_ENGINE_URL: str = "http://backtesting-engine:8007"
    PORTFOLIO_MANAGER_URL: str = "http://portfolio-manager:8008"
    ALERT_ENGINE_URL: str = "http://alert-engine:8009"
    ANALYTICS_ENGINE_URL: str = "http://analytics-engine:8010"
    TRADE_JOURNAL_URL: str = "http://trade-journal-engine:8011"
    ADMIN_DASHBOARD_URL: str = "http://admin-dashboard:8012"

    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173,http://localhost"

    AI_DECISION_THRESHOLD: float = 75.0

    ALLOW_PUBLIC_REGISTRATION: bool = True
    EXPOSE_SERVICE_REGISTRY: bool = True
    ENABLE_OPENAPI_DOCS: bool = True
    RATE_LIMIT_LOGIN_PER_MINUTE: int = 20
    RATE_LIMIT_ORDERS_PER_MINUTE: int = 30

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    ALERT_EMAIL_TO: str = ""


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    from trading_shared.security.production import validate_production_settings

    validate_production_settings(settings)
    return settings
