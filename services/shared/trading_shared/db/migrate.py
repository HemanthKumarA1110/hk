"""Lightweight schema patches for existing deployments."""

from sqlalchemy import text
from sqlalchemy.engine import Engine


def apply_patches(engine: Engine) -> None:
    patches = [
        "ALTER TABLE broker_orders ADD COLUMN IF NOT EXISTS execution_mode VARCHAR(16) DEFAULT 'live'",
        "CREATE INDEX IF NOT EXISTS ix_broker_orders_execution_mode ON broker_orders (execution_mode)",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS allowed_pages TEXT",
    ]
    with engine.begin() as conn:
        for statement in patches:
            conn.execute(text(statement))
