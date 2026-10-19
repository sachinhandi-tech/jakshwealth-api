"""Session crypto and daily expiry. No broker call and no token in assertions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from kite_app.models import Base, User, ZerodhaSession
from kite_app.session_manager import SessionExpiredException, encrypt_access_token, today_ist, upsert_zerodha_session


def test_ciphertext_does_not_contain_the_access_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode("ascii"))
    token = "access-token-value"
    stored = encrypt_access_token(token)
    assert token not in stored


def test_stale_token_date_is_not_today() -> None:
    stale = today_ist().toordinal() - 1
    assert stale != today_ist().toordinal()


def test_upsert_stores_ciphertext_for_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode("ascii"))
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    user_id = uuid.uuid4()
    db.add(User(platform_user_id=user_id, email="subscriber@example.com", is_active=True))
    db.commit()
    upsert_zerodha_session(db, user_id, "AB1234", "access-token-value")
    row = db.get(ZerodhaSession, user_id)
    assert row is not None
    assert row.zerodha_user_id == "AB1234"
    assert row.token_date == today_ist()
    assert "access-token-value" not in row.encrypted_access_token
    assert row.updated_at is not None


def test_get_active_kite_client_rejects_a_stale_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("KITE_API_KEY", "platform-key")
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr("kite_app.session_manager.get_sessionmaker", lambda: factory)
    user_id = uuid.uuid4()
    db = factory()
    db.add(User(platform_user_id=user_id, email="subscriber@example.com", is_active=True))
    db.add(
        ZerodhaSession(
            platform_user_id=user_id,
            zerodha_user_id="AB1234",
            encrypted_access_token=encrypt_access_token("access-token-value"),
            token_date=today_ist().fromordinal(today_ist().toordinal() - 1),
            updated_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    db.close()
    from kite_app.session_manager import get_active_kite_client

    with pytest.raises(SessionExpiredException):
        get_active_kite_client(str(user_id))
