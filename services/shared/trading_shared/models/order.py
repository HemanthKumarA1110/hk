"""Persisted broker order records."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from trading_shared.db.base import Base


class BrokerOrder(Base):
    __tablename__ = "broker_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    uniqueorderid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False)
    symboltoken: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    order_type: Mapped[str] = mapped_column(String(16), default="MARKET")
    product: Mapped[str] = mapped_column(String(16), default="INTRADAY")
    variety: Mapped[str] = mapped_column(String(16), default="NORMAL")
    status: Mapped[str] = mapped_column(String(32), default="submitted", index=True)
    stoploss: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_approved: Mapped[bool] = mapped_column(Boolean, default=True)
    risk_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    execution_mode: Mapped[str] = mapped_column(String(16), default="live", index=True)
    broker_response_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
