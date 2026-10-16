from pathlib import Path

from kite_app.kite_service import extract_request_token
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
