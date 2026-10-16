import json
from pathlib import Path

import importlib.util

SECURE_DATA_DIR = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "jw_secure_data_handler", SECURE_DATA_DIR / "handler.py"
)
handler = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(handler)

EVENT = {
    "httpMethod": "GET",
    "path": "/jw-api/secure-data/admin",
    "requestContext": {
        "authorizer": {
            "lanId": "TESTUSER01",
            "roles": "user",
            "principalId": "TESTUSER01",
            "requestId": "req-123",
        }
    },
}


def _body(response):
    return json.loads(response["body"])


def test_handler_admin_returns_feature_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("FEATURE_FLAGS_OVERRIDE_FILE", str(tmp_path / "feature_flags.local.json"))
    monkeypatch.delenv("ENABLE_AI_CHAT", raising=False)
    response = handler.handler(EVENT, None)
    assert response["statusCode"] == 200
    body = _body(response)
    assert body["enableAiChat"] is False
    assert body["features"]["aiChat"] is False


def test_handler_admin_features_updates_ai_chat_when_platform_enabled(tmp_path, monkeypatch):
    override_file = tmp_path / "feature_flags.local.json"
    monkeypatch.setenv("FEATURE_FLAGS_OVERRIDE_FILE", str(override_file))
    monkeypatch.setenv("ENABLE_AI_CHAT", "true")

    event = {
        **EVENT,
        "httpMethod": "POST",
        "path": "/jw-api/secure-data/admin/features",
        "body": json.dumps({"features": {"aiChat": True}}),
    }
    response = handler.handler(event, None)
    assert response["statusCode"] == 200
    body = _body(response)
    assert body["enableAiChat"] is True
    assert body["features"]["aiChat"] is True

    admin_response = handler.handler(EVENT, None)
    assert _body(admin_response)["features"]["aiChat"] is True


def test_handler_admin_features_rejects_ai_chat_when_platform_disabled(tmp_path, monkeypatch):
    override_file = tmp_path / "feature_flags.local.json"
    monkeypatch.setenv("FEATURE_FLAGS_OVERRIDE_FILE", str(override_file))
    monkeypatch.delenv("ENABLE_AI_CHAT", raising=False)

    event = {
        **EVENT,
        "httpMethod": "POST",
        "path": "/jw-api/secure-data/admin/features",
        "body": json.dumps({"features": {"aiChat": True}}),
    }
    response = handler.handler(event, None)
    assert response["statusCode"] == 400
    assert "ENABLE_AI_CHAT" in _body(response)["message"]
