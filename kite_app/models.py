"""Platform users and per-subscriber Zerodha sessions."""

from __future__ import annotations

import json
import os
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from typing import Optional

_SESSIONMAKER: Optional[sessionmaker] = None


class Base(DeclarativeBase):
    """Shared metadata for tenant tables."""


class User(Base):
    """Subscriber of the platform. Broker credentials are never stored here."""

    __tablename__ = "users"

    platform_user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SignalScanJob(Base):
    """One Nifty 100 scan started by the desk and finished after the HTTP request returns."""

    __tablename__ = "signal_scan_jobs"

    job_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    credential_blob: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ZerodhaSession(Base):
    """One Kite access token per subscriber, encrypted, valid for a single IST date."""

    __tablename__ = "zerodha_sessions"

    platform_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.platform_user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    zerodha_user_id: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    token_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def load_platform_config() -> None:
    """Fill database, encryption, and Kite app settings from Secrets Manager when they are not already set."""
    needs_db = not os.environ.get("DATABASE_URL", "").strip() or not os.environ.get("FERNET_KEY", "").strip()
    needs_kite = not os.environ.get("KITE_API_KEY", "").strip() or not os.environ.get("KITE_API_SECRET", "").strip()
    if not needs_db and not needs_kite:
        return
    secret_id = os.environ.get("KITE_DB_SECRET_ID", "").strip()
    if not secret_id:
        return
    try:
        import boto3

        raw = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)["SecretString"]
    except Exception:
        return
    payload = json.loads(raw)
    if not os.environ.get("DATABASE_URL", "").strip():
        os.environ["DATABASE_URL"] = str(payload["url"])
    for env_name, key in (
        ("FERNET_KEY", "fernet_key"),
        ("KITE_STATE_SECRET", "state_secret"),
        ("KITE_API_KEY", "kite_api_key"),
        ("KITE_API_SECRET", "kite_api_secret"),
    ):
        value = str(payload.get(key) or "").strip()
        if value and not os.environ.get(env_name, "").strip():
            os.environ[env_name] = value


def get_sessionmaker() -> sessionmaker:
    """Return a process-wide session factory. Tables are created on first use."""
    global _SESSIONMAKER
    if _SESSIONMAKER is None:
        load_platform_config()
        url = os.environ["DATABASE_URL"]
        engine_kwargs: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            engine_kwargs = {"connect_args": {"check_same_thread": False}}
        engine = create_engine(url, **engine_kwargs)
        Base.metadata.create_all(engine)
        _SESSIONMAKER = sessionmaker(bind=engine, expire_on_commit=False)
    return _SESSIONMAKER
