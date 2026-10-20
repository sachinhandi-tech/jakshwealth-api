"""Connections for jakshwealth_identity and jakshwealth_trading on the existing RDS instance."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

_LOCK = threading.Lock()
_READY = False
_IDENTITY: sessionmaker | None = None
_TRADING: sessionmaker | None = None
_ADMIN: sessionmaker | None = None
_ROOT = Path(__file__).resolve().parent


def reset_for_tests() -> None:
    global _READY, _IDENTITY, _TRADING, _ADMIN
    _READY = False
    _IDENTITY = None
    _TRADING = None
    _ADMIN = None


def identity_session() -> Session:
    _prepare()
    assert _IDENTITY is not None
    return _IDENTITY()


def trading_session() -> Session:
    _prepare()
    assert _TRADING is not None
    return _TRADING()


def admin_identity_session() -> Session:
    """Master connection. The desk role can read users and cannot insert one."""
    global _ADMIN
    _prepare()
    if _ADMIN is None:
        url = _identity_url()
        kwargs: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs = {"connect_args": {"check_same_thread": False}}
        _ADMIN = sessionmaker(bind=create_engine(url, **kwargs), expire_on_commit=False)
    return _ADMIN()


def _prepare() -> None:
    global _READY, _IDENTITY, _TRADING
    if _READY:
        return
    with _LOCK:
        if _READY:
            return
        identity = _identity_url()
        trading = _trading_url()
        if identity.startswith("postgresql"):
            _ensure_postgres_database(identity)
            _ensure_postgres_database(trading)
        _upgrade(identity, _ROOT / "alembic_identity")
        _upgrade(trading, _ROOT / "alembic_trading")
        if identity.startswith("postgresql"):
            _copy_legacy_rows(identity)
        _IDENTITY = _factory(identity)
        _TRADING = _factory(trading)
        _READY = True


def _identity_url() -> str:
    override = os.environ.get("IDENTITY_DATABASE_URL", "").strip()
    if override:
        return override
    return _swap_database(_required_database_url(), "jakshwealth_identity")


def _trading_url() -> str:
    override = os.environ.get("TRADING_DATABASE_URL", "").strip()
    if override:
        return override
    return _swap_database(_required_database_url(), "jakshwealth_trading")


def _required_database_url() -> str:
    from kite_app.models import load_platform_config

    load_platform_config()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


def _swap_database(url: str, name: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(path=f"/{name}"))


def _ensure_postgres_database(target: str) -> None:
    name = urlparse(target).path.lstrip("/")
    admin = _swap_database(os.environ["DATABASE_URL"], "jakshwealth")
    engine = create_engine(admin, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": name},
            ).scalar()
            if exists:
                return
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        engine.dispose()


def _upgrade(url: str, script: Path) -> None:
    from alembic.config import Config
    from alembic import command

    config = Config()
    config.set_main_option("script_location", str(script))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")


def _factory(url: str) -> sessionmaker:
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
    engine = create_engine(url, **kwargs)
    _limit_to_desk_role(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _limit_to_desk_role(engine) -> None:
    """Application work runs as jakshwealth_desk. Alembic keeps the master connection."""
    if engine.dialect.name != "postgresql":
        return
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _set_role(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("SET ROLE jakshwealth_desk")
        cursor.close()


def _copy_legacy_rows(identity_url: str) -> None:
    """Copy users and zerodha_sessions ciphertext. The Fernet key is unchanged."""
    source = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    dest = create_engine(identity_url, pool_pre_ping=True)
    try:
        with source.connect() as src, dest.begin() as dst:
            users = src.execute(text(
                "SELECT platform_user_id, email, is_active FROM users"
            )).mappings()
            for row in users:
                dst.execute(
                    text(
                        """
                        INSERT INTO users (platform_user_id, email, is_active)
                        VALUES (:platform_user_id, :email, :is_active)
                        ON CONFLICT (platform_user_id) DO NOTHING
                        """
                    ),
                    dict(row),
                )
            sessions = src.execute(text(
                """
                SELECT platform_user_id, zerodha_user_id, encrypted_access_token, token_date, updated_at
                FROM zerodha_sessions
                """
            )).mappings()
            for row in sessions:
                dst.execute(
                    text(
                        """
                        INSERT INTO kite_sessions (
                            platform_user_id, zerodha_user_id, encrypted_access_token,
                            encrypted_public_token, encrypted_refresh_token, token_date, updated_at
                        )
                        VALUES (
                            :platform_user_id, :zerodha_user_id, :encrypted_access_token,
                            NULL, NULL, :token_date, :updated_at
                        )
                        ON CONFLICT (platform_user_id) DO NOTHING
                        """
                    ),
                    dict(row),
                )
    except Exception as exc:
        logging.getLogger("kite_app.persistence").info("legacy copy skipped %s", type(exc).__name__)
        return
    finally:
        source.dispose()
        dest.dispose()
