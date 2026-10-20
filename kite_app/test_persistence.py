"""Identity and trading persistence. No live Kite call."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from kiteconnect.exceptions import KiteException
from sqlalchemy import func, select

from kite_app.auth_router import _sign_desk_state, _sign_state, zerodha_callback, zerodha_login
from kite_app.gtt_orders import clear_recent_placements, live_gtt
from kite_app.identity_models import IdentityUser, KiteSessionRow, LoginEvent
from kite_app.persistence import identity_session, reset_for_tests, trading_session
from kite_app.session_manager import SessionExpiredException, get_active_kite_client, purge_expired_sessions, today_ist
from kite_app.test_gtt_orders import kite, order
from kite_app.trading_models import GttAttempt, OrderEvent, RejectedPostback, TradeRow
from kite_app.trading_store import _RECONCILED, accept_postback, insert_order_event, reconcile_book


@pytest.fixture
def databases(tmp_path, monkeypatch):
    identity = tmp_path / "identity.db"
    trading = tmp_path / "trading.db"
    monkeypatch.setenv("IDENTITY_DATABASE_URL", "sqlite:///" + identity.as_posix())
    monkeypatch.setenv("TRADING_DATABASE_URL", "sqlite:///" + trading.as_posix())
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode("ascii"))
    monkeypatch.setenv("KITE_API_KEY", "platformkey1234")
    monkeypatch.setenv("KITE_API_SECRET", "server-secret")
    monkeypatch.setenv("KITE_STATE_SECRET", "state-secret")
    monkeypatch.setenv("KITE_SESSION_PATH", str(tmp_path / "session.json"))
    monkeypatch.delenv("KITE_SESSION_BUCKET", raising=False)
    monkeypatch.delenv("SCANNER_CACHE_BUCKET", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_for_tests()
    _RECONCILED.clear()
    yield identity, trading
    reset_for_tests()
    _RECONCILED.clear()


def _user(active: bool = True) -> uuid.UUID:
    user_id = uuid.uuid4()
    db = identity_session()
    db.add(IdentityUser(platform_user_id=user_id, email=f"{user_id}@example.com", is_active=active))
    db.commit()
    db.close()
    return user_id


class _Kite:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def generate_session(self, request_token: str, api_secret: str) -> dict:
        return {
            "user_id": "AB1234",
            "user_name": "Ada",
            "user_shortname": "A",
            "email": "ada@example.com",
            "user_type": "individual",
            "broker": "ZERODHA",
            "exchanges": ["NSE"],
            "products": ["CNC"],
            "order_types": ["LIMIT"],
            "access_token": "access-token-value",
            "public_token": "public-token-value",
            "login_time": "2026-10-20 09:00:00",
            "meta": {"demat_consent": "physical"},
            "avatar_url": "https://example.invalid/a",
        }


def test_callback_stores_one_event_and_encrypted_session(databases, monkeypatch):
    identity, _trading = databases
    user_id = _user()
    monkeypatch.setattr("kite_app.auth_router.KiteConnect", _Kite)
    monkeypatch.setattr("kite_app.auth_router.SessionStore.save", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("plaintext")))
    response = zerodha_callback(request_token="one-time-request", state=_sign_state(user_id), status="success")
    assert "access-token-value" not in str(response.headers.get("location"))
    blob = identity.read_bytes()
    assert b"access-token-value" not in blob
    assert b"public-token-value" not in blob
    assert b"one-time-request" not in blob
    assert b"server-secret" not in blob
    assert not (databases[0].parent / "session.json").exists()
    db = identity_session()
    events = db.scalars(select(LoginEvent)).all()
    sessions = db.scalars(select(KiteSessionRow)).all()
    db.close()
    assert len(events) == 1
    assert events[0].outcome == "completed"
    assert events[0].source == "auth_callback"
    assert events[0].api_key_last4 == "1234"
    assert events[0].api_key_sha256 == hashlib.sha256(b"platformkey1234").hexdigest()
    assert len(sessions) == 1
    assert sessions[0].encrypted_public_token
    assert sessions[0].encrypted_refresh_token is None


def test_failed_exchange_writes_an_event_and_no_session(databases, monkeypatch):
    identity, _trading = databases
    user_id = _user()

    class Failed(_Kite):
        def generate_session(self, request_token: str, api_secret: str) -> dict:
            raise KiteException("exchange failed")

    monkeypatch.setattr("kite_app.auth_router.KiteConnect", Failed)
    with pytest.raises(HTTPException) as caught:
        zerodha_callback(request_token="one-time-request", state=_sign_state(user_id), status="success")
    assert caught.value.status_code == 401
    db = identity_session()
    events = db.scalars(select(LoginEvent)).all()
    sessions = db.scalars(select(KiteSessionRow)).all()
    db.close()
    assert len(events) == 1
    assert events[0].outcome == "exchange_failed"
    assert sessions == []
    assert b"one-time-request" not in identity.read_bytes()


def test_second_login_replaces_ciphertext_and_appends_an_event(databases, monkeypatch):
    user_id = _user()
    tokens = iter(["access-token-value", "access-token-second"])

    class Rotating(_Kite):
        def generate_session(self, request_token: str, api_secret: str) -> dict:
            payload = _Kite.generate_session(self, request_token, api_secret)
            payload["access_token"] = next(tokens)
            return payload

    monkeypatch.setattr("kite_app.auth_router.KiteConnect", Rotating)
    zerodha_callback(request_token="one-time-request", state=_sign_state(user_id), status="success")
    zerodha_callback(request_token="one-time-request", state=_sign_state(user_id), status="success")
    db = identity_session()
    events = db.scalars(select(LoginEvent)).all()
    row = db.get(KiteSessionRow, user_id)
    db.close()
    assert len(events) == 2
    assert row is not None
    assert "access-token-second" not in row.encrypted_access_token


def test_purge_removes_only_the_old_session_row(databases):
    user_id = _user()
    db = identity_session()
    db.add(LoginEvent(
        event_id=uuid.uuid4(),
        platform_user_id=user_id,
        received_at=datetime.now(timezone.utc),
        source="auth_callback",
        outcome="completed",
        zerodha_user_id="AB1234",
    ))
    db.add(KiteSessionRow(
        platform_user_id=user_id,
        zerodha_user_id="AB1234",
        encrypted_access_token="ciphertext",
        token_date=today_ist() - timedelta(days=1),
        updated_at=datetime.now(timezone.utc),
    ))
    db.commit()
    db.close()
    assert purge_expired_sessions() == 1
    db = identity_session()
    assert db.get(KiteSessionRow, user_id) is None
    assert db.scalar(select(func.count()).select_from(LoginEvent)) == 1
    db.close()


def test_missing_platform_user_does_not_store_a_token(databases, monkeypatch):
    _user()
    called = {"n": 0}

    class Counting(_Kite):
        def generate_session(self, request_token: str, api_secret: str) -> dict:
            called["n"] += 1
            return {}

    monkeypatch.setattr("kite_app.auth_router.KiteConnect", Counting)
    with pytest.raises(HTTPException) as caught:
        zerodha_callback(request_token="one-time-request", state=_sign_desk_state(), status="success")
    assert caught.value.status_code == 403
    assert called["n"] == 0
    db = identity_session()
    event = db.scalar(select(LoginEvent))
    assert event is not None
    assert event.outcome == "subscriber_inactive"
    assert db.scalar(select(func.count()).select_from(KiteSessionRow)) == 0
    db.close()


def test_first_sign_in_opens_the_account(databases, monkeypatch):
    class LoginKite(_Kite):
        def login_url(self) -> str:
            return "https://kite.zerodha.com/connect/login?v=3&api_key=platformkey1234"

    monkeypatch.setattr("kite_app.auth_router.KiteConnect", LoginKite)
    started = zerodha_login(None)
    assert started.status_code == 302
    assert "kite.zerodha.com" in started.headers["location"]
    finished = zerodha_callback(request_token="one-time-request", state=_sign_desk_state(), status="success")
    assert finished.status_code == 302
    assert "access-token-value" not in str(finished.headers.get("location"))
    db = identity_session()
    user = db.scalar(select(IdentityUser))
    event = db.scalar(select(LoginEvent))
    session_row = db.scalar(select(KiteSessionRow))
    db.close()
    assert user is not None
    assert user.email == "ada@example.com"
    assert user.is_active is True
    assert event.outcome == "completed"
    assert event.platform_user_id == user.platform_user_id
    assert session_row.platform_user_id == user.platform_user_id


def test_stale_identity_session_is_rejected(databases):
    user_id = _user()
    db = identity_session()
    db.add(KiteSessionRow(
        platform_user_id=user_id,
        zerodha_user_id="AB1234",
        encrypted_access_token="ciphertext",
        token_date=today_ist().fromordinal(today_ist().toordinal() - 1),
        updated_at=datetime.now(timezone.utc),
    ))
    db.commit()
    db.close()
    with pytest.raises(SessionExpiredException):
        get_active_kite_client(str(user_id))


def test_confirmed_gtt_is_stored_once_and_a_failure_is_not_retried(databases):
    clear_recent_placements()
    user_id = _user()
    client = kite()
    live_gtt(client, [order()], confirm_live=True, platform_user_id=user_id, zerodha_user_id="AB1234")
    db = trading_session()
    rows = db.scalars(select(GttAttempt)).all()
    db.close()
    assert len(rows) == 1
    assert rows[0].trigger_id == "4242"
    assert rows[0].transaction_type == "BUY"
    assert rows[0].exchange == "NSE"
    assert rows[0].product == "CNC"
    assert rows[0].quantity == 1
    assert client.place_gtt.call_count == 1

    clear_recent_placements()
    failed = kite()
    failed.place_gtt.side_effect = KiteException("rejected by kite")
    live_gtt(failed, [order()], confirm_live=True, platform_user_id=user_id, zerodha_user_id="AB1234")
    assert failed.place_gtt.call_count == 1
    db = trading_session()
    stored = db.scalars(select(GttAttempt)).all()
    db.close()
    assert len(stored) == 2
    assert stored[1].trigger_id is None
    assert stored[1].kite_error_text == "rejected by kite"
    assert all(row.transaction_type != "SELL" for row in stored)


def test_postback_is_stored_once_and_a_bad_checksum_is_rejected(databases):
    secret = "server-secret"
    body = {
        "user_id": "AB1234",
        "order_id": "100",
        "order_timestamp": "2026-10-20 10:00:00",
        "status": "COMPLETE",
        "filled_quantity": 1,
        "guid": "g-1",
        "tradingsymbol": "INFY",
        "transaction_type": "BUY",
    }
    body["checksum"] = hashlib.sha256(f"{body['order_id']}{body['order_timestamp']}{secret}".encode()).hexdigest()
    raw = json.dumps(body).encode()
    assert accept_postback(raw)["checksum_valid"] is True
    assert accept_postback(raw)["checksum_valid"] is True
    bad = dict(body)
    bad["checksum"] = "0" * 64
    assert accept_postback(json.dumps(bad).encode())["checksum_valid"] is False
    db = trading_session()
    assert db.scalar(select(func.count()).select_from(OrderEvent)) == 1
    rejected = db.scalars(select(RejectedPostback)).all()
    assert len(rejected) == 1
    assert "COMPLETE" in rejected[0].raw_body
    db.close()


def test_orders_replay_does_not_duplicate_events(databases):
    payload = {
        "order_id": "100",
        "order_timestamp": "2026-10-20 10:00:00",
        "status": "COMPLETE",
        "filled_quantity": 1,
        "guid": "g-1",
        "placed_by": "AB1234",
    }
    trade = {"trade_id": "t-1", "order_id": "100", "quantity": 1, "transaction_type": "BUY"}

    class Book:
        def __init__(self) -> None:
            self.calls = 0

        def orders(self):
            self.calls += 1
            return [payload]

        def order_history(self, order_id):
            return [payload]

        def trades(self):
            return [trade]

    book = Book()
    user_id = uuid.uuid4()
    token_date = today_ist().isoformat()
    reconcile_book(book, user_id, "AB1234", token_date)
    reconcile_book(book, user_id, "AB1234", token_date)
    assert insert_order_event("orders_list", payload, checksum_valid=None, raw=payload) is False
    db = trading_session()
    assert db.scalar(select(func.count()).select_from(OrderEvent).where(OrderEvent.source == "orders_list")) == 1
    assert db.scalar(select(func.count()).select_from(OrderEvent).where(OrderEvent.source == "order_history")) == 1
    assert db.scalar(select(func.count()).select_from(TradeRow)) == 1
    db.close()
    assert book.calls == 1


def test_sign_in_stays_open_outside_algo_hours(databases, monkeypatch):
    monkeypatch.setattr("kite_app.kite_service.desk_is_open", lambda now=None: False)
    monkeypatch.setattr("kite_app.auth_router.KiteConnect", _Kite)
    user_id = _user()
    response = zerodha_callback(request_token="one-time-request", state=_sign_state(user_id), status="success")
    assert response.status_code == 302
    db = identity_session()
    event = db.scalar(select(LoginEvent))
    db.close()
    assert event.outcome == "completed"


def test_request_id_is_stored_on_the_login_event(databases):
    from kite_app.identity_store import record_login
    from kite_app.request_context import request_id_var

    user_id = _user()
    token = request_id_var.set("req-123")
    try:
        record_login(
            source="kite_login",
            outcome="subscriber_inactive",
            platform_user_id=user_id,
            api_key="platformkey1234",
            session=None,
        )
    finally:
        request_id_var.reset(token)
    db = identity_session()
    event = db.scalar(select(LoginEvent))
    db.close()
    assert event.request_id == "req-123"


def test_desk_session_requires_the_platform_user(databases):
    from kite_app.identity_store import current_desk_session
    from kite_app.session_manager import encrypt_access_token

    user_id = _user()
    db = identity_session()
    db.add(KiteSessionRow(
        platform_user_id=user_id,
        zerodha_user_id="AB1234",
        encrypted_access_token=encrypt_access_token("access-token-value"),
        token_date=today_ist(),
        updated_at=datetime.now(timezone.utc),
    ))
    db.commit()
    db.close()
    assert current_desk_session(None) is None
    found = current_desk_session(user_id)
    assert found is not None
    assert found["platform_user_id"] == user_id
    assert found["user_id"] == "AB1234"


def test_socket_order_postback_is_stored_once(databases):
    from kite_app.trading_store import persist_socket_order

    payload = {
        "order_id": "200",
        "order_timestamp": "2026-10-20 11:00:00",
        "status": "COMPLETE",
        "filled_quantity": 1,
        "guid": "g-socket",
        "placed_by": "AB1234",
        "transaction_type": "SELL",
    }
    assert persist_socket_order(payload) is True
    assert persist_socket_order(payload) is False
    db = trading_session()
    rows = db.scalars(select(OrderEvent)).all()
    db.close()
    assert len(rows) == 1
    assert rows[0].source == "postback"
    assert rows[0].transaction_type == "SELL"


def test_order_command_stores_the_id_and_not_a_fill(databases):
    from kite_app.trading_models import OrderCommand
    from kite_app.trading_store import submit_order_command

    class Broker:
        def place_order(self, **parameters):
            return {"order_id": "555"}

    result = submit_order_command(Broker(), "place", {"variety": "regular", "tradingsymbol": "INFY", "transaction_type": "BUY", "quantity": 1})
    assert result == {"order_id": "555"}
    db = trading_session()
    command = db.scalar(select(OrderCommand))
    events = db.scalar(select(func.count()).select_from(OrderEvent))
    db.close()
    assert command.order_id == "555"
    assert command.action == "place"
    assert events == 0


def test_post_login_uses_the_server_secret_and_hides_the_token(databases, monkeypatch):
    monkeypatch.setattr("kite_app.kite_service.desk_is_open", lambda now=None: True)
    user_id = _user()
    seen = {}

    class Fake:
        def __init__(self, api_key: str) -> None:
            seen["api_key"] = api_key

        def generate_session(self, request_token: str, api_secret: str) -> dict:
            seen["api_secret"] = api_secret
            return {"access_token": "access-token-value", "user_id": "AB1234", "user_name": "Ada"}

        def set_access_token(self, token: str) -> None:
            return None

        def profile(self) -> dict:
            return {"user_id": "AB1234", "user_name": "Ada", "products": ["CNC"], "exchanges": ["NSE"]}

    monkeypatch.setattr("kite_app.kite_service.KiteConnect", Fake)
    from kite_app.kite_service import KiteService

    result = KiteService().login("one-time-request", user_id)
    assert result["authenticated"] is True
    assert result["user_id"] == "AB1234"
    assert result["platform_user_id"] == str(user_id)
    assert "access_token" not in result
    assert seen["api_key"] == "platformkey1234"
    assert seen["api_secret"] == "server-secret"
    db = identity_session()
    event = db.scalar(select(LoginEvent).where(LoginEvent.source == "kite_login"))
    assert event is not None
    assert event.outcome == "completed"
    db.close()
    identity, _trading = databases
    assert b"access-token-value" not in identity.read_bytes()
    assert b"one-time-request" not in identity.read_bytes()


def test_skipped_gtt_is_stored_without_a_second_place(databases):
    from kite_app.test_gtt_orders import active_buy

    clear_recent_placements()
    user_id = _user()
    client = kite(gtts=[active_buy("SIEMENS", 4242, 3903.3)])
    row = live_gtt(client, [order()], confirm_live=True, platform_user_id=user_id, zerodha_user_id="AB1234")[0]
    assert row["message"] == "Skipped: buy GTT already active."
    client.place_gtt.assert_not_called()
    db = trading_session()
    stored = db.scalar(select(GttAttempt))
    db.close()
    assert stored is not None
    assert stored.outcome == "Skipped: buy GTT already active."
    assert stored.trigger_id == "4242"
