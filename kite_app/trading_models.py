"""Tables in jakshwealth_trading. Created by Alembic, not create_all."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class TradingBase(DeclarativeBase):
    """Metadata for the trading database only."""


class GttAttempt(TradingBase):
    __tablename__ = "gtt_attempts"

    attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    platform_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    zerodha_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tradingsymbol: Mapped[str | None] = mapped_column(Text, nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(16), nullable=True)
    trigger_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    trigger_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_price: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_type: Mapped[str | None] = mapped_column(String(8), nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    product: Mapped[str | None] = mapped_column(String(16), nullable=True)
    confirm_live: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    trigger_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    kite_error_text: Mapped[str | None] = mapped_column(Text, nullable=True)


class OrderCommand(TradingBase):
    """Filled only when this app calls place, modify, or cancel. It does not do that today."""

    __tablename__ = "order_commands"

    command_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    platform_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    zerodha_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    variety: Mapped[str | None] = mapped_column(Text, nullable=True)
    exchange: Mapped[str | None] = mapped_column(Text, nullable=True)
    tradingsymbol: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[str | None] = mapped_column(Text, nullable=True)
    product: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_price: Mapped[str | None] = mapped_column(Text, nullable=True)
    validity: Mapped[str | None] = mapped_column(Text, nullable=True)
    disclosed_quantity: Mapped[str | None] = mapped_column(Text, nullable=True)
    tag: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_failure_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OrderEvent(TradingBase):
    __tablename__ = "order_events"

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    zerodha_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checksum_valid: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    placed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    exchange_order_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_order_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_message_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_timestamp: Mapped[str | None] = mapped_column(Text, nullable=True)
    exchange_update_timestamp: Mapped[str | None] = mapped_column(Text, nullable=True)
    exchange_timestamp: Mapped[str | None] = mapped_column(Text, nullable=True)
    variety: Mapped[str | None] = mapped_column(Text, nullable=True)
    modified: Mapped[str | None] = mapped_column(Text, nullable=True)
    exchange: Mapped[str | None] = mapped_column(Text, nullable=True)
    tradingsymbol: Mapped[str | None] = mapped_column(Text, nullable=True)
    instrument_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    validity: Mapped[str | None] = mapped_column(Text, nullable=True)
    product: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[str | None] = mapped_column(Text, nullable=True)
    disclosed_quantity: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[str | None] = mapped_column(Text, nullable=True)
    trigger_price: Mapped[str | None] = mapped_column(Text, nullable=True)
    average_price: Mapped[str | None] = mapped_column(Text, nullable=True)
    filled_quantity: Mapped[str | None] = mapped_column(Text, nullable=True)
    pending_quantity: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_quantity: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_protection: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tag: Mapped[str | None] = mapped_column(Text, nullable=True)
    guid: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class TradeRow(TradingBase):
    __tablename__ = "trades"

    trade_row_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trade_id: Mapped[str] = mapped_column(Text, nullable=False)
    order_id: Mapped[str] = mapped_column(Text, nullable=False)
    exchange: Mapped[str | None] = mapped_column(Text, nullable=True)
    tradingsymbol: Mapped[str | None] = mapped_column(Text, nullable=True)
    instrument_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    product: Mapped[str | None] = mapped_column(Text, nullable=True)
    average_price: Mapped[str | None] = mapped_column(Text, nullable=True)
    quantity: Mapped[str | None] = mapped_column(Text, nullable=True)
    exchange_order_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    transaction_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    fill_timestamp: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_timestamp: Mapped[str | None] = mapped_column(Text, nullable=True)
    exchange_timestamp: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class RejectedPostback(TradingBase):
    __tablename__ = "rejected_postbacks"

    rejected_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_body: Mapped[str] = mapped_column(Text, nullable=False)
