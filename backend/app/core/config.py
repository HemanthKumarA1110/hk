from pydantic import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./dev.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    JWT_SECRET: str = "change_me"
    ENV: str = "dev"

    ANGEL_CLIENT_ID: str = ""
    ANGEL_CLIENT_SECRET: str = ""
    ANGEL_API_KEY: str = ""
    ANGEL_USER_ID: str = ""
    ANGEL_PASSWORD: str = ""
    ANGEL_2FA_PIN: str = ""

    class Config:
        env_file = "../../.env"

settings = Settings()
