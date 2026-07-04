from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from trading_shared.config import get_settings
from trading_shared.db.base import Base

_settings = get_settings()
engine = create_engine(
    _settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=15,
    max_overflow=30,
    pool_recycle=300,
    pool_timeout=60,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    from trading_shared.models import ai, audit_log, backtest, broker_session, market, order, strategy_signal, user  # noqa: F401

    Base.metadata.create_all(bind=engine)
    from trading_shared.db.migrate import apply_patches

    apply_patches(engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
