from datetime import datetime, timezone
from pathlib import Path

import pytest

from kite_app.kite_service import access_token_expired, extract_request_token
from kite_app.session_store import SessionStore


def test_extract_request_token_from_redirect_url():
    raw = "https://127.0.0.1/redirect?request_token=abc123&action=login&status=success"
    assert extract_request_token(raw) == "abc123"


def test_extract_request_token_plain_value():
    assert extract_request_token("  qzToken  ") == "qzToken"


def test_session_round_trip_keeps_token_on_disk_only(tmp_path: Path):
    store = SessionStore(tmp_path / "session.json")
    store.save(
        {
            "api_key": "key",
            "access_token": "secret-token",
            "user_id": "AB1234",
            "user_name": "Ada",
            "saved_at": "2026-10-16T00:00:00+00:00",
            "api_secret": "should-not-persist",
        }
    )
    loaded = store.load()
    assert loaded is not None
    assert loaded["access_token"] == "secret-token"
    assert "api_secret" not in loaded
    text = (tmp_path / "session.json").read_text(encoding="utf-8")
    assert "should-not-persist" not in text
    store.clear()
    assert store.load() is None


def test_shared_session_is_reloaded_from_s3(monkeypatch, tmp_path: Path):
    objects: dict[tuple[str, str], bytes] = {}

    class FakeBody:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def read(self) -> bytes:
            return self.payload

    class MissingKey(Exception):
        def __init__(self) -> None:
            super().__init__("missing")
            self.response = {"Error": {"Code": "NoSuchKey", "Message": "missing"}}

    class FakeS3:
        def put_object(self, Bucket, Key, Body, ContentType=None):
            objects[(Bucket, Key)] = Body if isinstance(Body, bytes) else Body.encode("utf-8")

        def get_object(self, Bucket, Key):
            if (Bucket, Key) not in objects:
                raise MissingKey()
            return {"Body": FakeBody(objects[(Bucket, Key)])}

        def delete_object(self, Bucket, Key):
            objects.pop((Bucket, Key), None)

    monkeypatch.setenv("KITE_SESSION_BUCKET", "jakshwealth-artifacts-dev-aps2")
    monkeypatch.setenv("KITE_SESSION_KEY", "kite-session/session.json")
    import boto3

    monkeypatch.setattr(boto3, "client", lambda service: FakeS3())
    first = SessionStore(tmp_path / "one" / "session.json")
    first.save(
        {
            "api_key": "key",
            "access_token": "secret-token",
            "user_id": "AB1234",
            "user_name": "Ada",
            "saved_at": "2026-10-20T04:00:00+00:00",
        }
    )
    second = SessionStore(tmp_path / "two" / "session.json")
    loaded = second.load()
    assert loaded is not None
    assert loaded["access_token"] == "secret-token"
    first.clear()
    assert second.load() is None


def test_access_token_lasts_until_the_next_ist_morning():
    saved = "2026-10-19T16:30:00+00:00"
    assert access_token_expired(saved, datetime(2026, 10, 20, 0, 29, tzinfo=timezone.utc)) is False
    assert access_token_expired(saved, datetime(2026, 10, 20, 0, 30, tzinfo=timezone.utc)) is True


def test_algo_orders_are_accepted_any_day(monkeypatch):
    from kite_app.main import LiveGttRequest, algo_live_gtt

    monkeypatch.setattr(
        "kite_app.main.service.require_session",
        lambda: {"platform_user_id": None, "user_id": "AB1234"},
    )
    monkeypatch.setattr("kite_app.main.service._require_client", lambda: object())
    seen = {}

    def place(kite, orders, confirm_live, platform_user_id=None, zerodha_user_id=None):
        seen["confirm"] = confirm_live
        seen["user"] = zerodha_user_id
        return [{"symbol": "INFY"}]

    monkeypatch.setattr("kite_app.main.live_gtt", place)
    result = algo_live_gtt(LiveGttRequest(confirm_live=True, orders=[]))
    assert result == {"orders": [{"symbol": "INFY"}]}
    assert seen == {"confirm": True, "user": "AB1234"}
