"""Tables in jakshwealth_identity. Created by Alembic, not create_all."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, Date, DateTime, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class IdentityBase(DeclarativeBase):
    """Metadata for the identity database only."""


class IdentityUser(IdentityBase):
    """Platform user copied from jakshwealth.users. Broker credentials are not stored here."""

    __tablename__ = "users"

    platform_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False)


class LoginEvent(IdentityBase):
    """Append-only login audit. Replacing a session does not delete these rows."""

    __tablename__ = "login_events"

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    platform_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    request_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    zerodha_user_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    user_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_shortname: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    broker: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    exchanges: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    products: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    order_types: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    login_time: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    api_key_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    api_key_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class KiteSessionRow(IdentityBase):
    """Current encrypted Kite session for one platform user."""

    __tablename__ = "kite_sessions"

    platform_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    zerodha_user_id: Mapped[str] = mapped_column(String(32), nullable=False)
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_public_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    encrypted_refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_date: Mapped[date] = mapped_column(Date, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
