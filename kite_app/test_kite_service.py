from datetime import datetime, timezone
from pathlib import Path

import pytest

from kite_app.kite_service import access_token_expired, desk_is_open, extract_request_token
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


def test_algo_orders_are_refused_outside_weekday_hours(monkeypatch):
    from fastapi import HTTPException

    from kite_app.main import LiveGttRequest, algo_live_gtt

    monkeypatch.setattr("kite_app.main.desk_is_open", lambda now=None: False)
    with pytest.raises(HTTPException) as caught:
        algo_live_gtt(LiveGttRequest(confirm_live=True, orders=[]))
    assert caught.value.status_code == 403
    assert caught.value.detail == "Algo orders run on weekdays from 9:00 AM to 4:00 PM IST."


def test_desk_is_open_on_weekdays_from_nine_until_four():
    monday_open = datetime(2026, 10, 19, 3, 30, tzinfo=timezone.utc)
    monday_close = datetime(2026, 10, 19, 10, 30, tzinfo=timezone.utc)
    friday_afternoon = datetime(2026, 10, 23, 9, 0, tzinfo=timezone.utc)
    saturday = datetime(2026, 10, 24, 4, 30, tzinfo=timezone.utc)
    assert desk_is_open(monday_open) is True
    assert desk_is_open(monday_close) is False
    assert desk_is_open(friday_afternoon) is True
    assert desk_is_open(saturday) is False
