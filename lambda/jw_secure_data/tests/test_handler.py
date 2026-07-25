import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

SECURE_DATA_DIR = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "jw_secure_data_handler", SECURE_DATA_DIR / "handler.py"
)
handler = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(handler)

EVENT = {
    "httpMethod": "GET",
    "path": "/jw-api/secure-data",
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


def test_handler_allows_get():
    response = handler.handler(EVENT, None)
    assert response["statusCode"] == 200
    body = _body(response)
    assert body["lanId"] == "TESTUSER01"
    assert body["roles"] == ["user"]


def test_handler_allows_post():
    event = {**EVENT, "httpMethod": "POST"}
    response = handler.handler(event, None)
    assert response["statusCode"] == 200
    body = _body(response)
    assert body["lanId"] == "TESTUSER01"


def test_handler_rejects_unsupported_method():
    event = {**EVENT, "httpMethod": "PATCH"}
    response = handler.handler(event, None)
    assert response["statusCode"] == 405


FETCH_CHARTS_EVENT = {
    **EVENT,
    "httpMethod": "POST",
    "path": "/jw-api/secure-data/fetch-charts",
    "body": json.dumps(
        {
            "dashboard": "proof-points",
            "designation": "ccd",
            "viewId": "volume",
            "timeline": "ytd",
            "filters": {
                "crrMarket": [],
                "providerNetwork": [],
                "specialtyCategory": [],
                "specialtyType": [],
                "episodeCategory": [],
                "memberProduct": [],
            },
        }
    ),
}


@patch("databricks_client.is_configured", return_value=False)
def test_handler_fetch_charts_returns_chart_list(_mock_configured):
    response = handler.handler(FETCH_CHARTS_EVENT, None)
    assert response["statusCode"] == 200
    body = _body(response)
    assert len(body["charts"]) == 2
    doughnut = body["charts"][0]
    assert set(doughnut.keys()) == {
        "chartId",
        "chartType",
        "title",
        "explanation",
        "labels",
        "data",
        "centerLines",
        "hoverMessages",
    }
    assert doughnut["title"] == "Provider Group Volume"
    assert doughnut["centerLines"]
    assert doughnut["chartId"] == "ccd-volume-provider-groups"
    assert doughnut["chartType"] == "doughnut"
    assert doughnut["labels"]
    assert doughnut["data"]
    provider_volume = body["charts"][1]
    assert provider_volume["chartId"] == "ccd-volume-provider-volume"
    assert provider_volume["title"] == "Provider Volume"
    assert provider_volume["labels"] == ["CCD", "Non CCD"]
    assert len(provider_volume["data"]) == 2


def test_handler_fetch_charts_requires_view_id():
    event = {
        **FETCH_CHARTS_EVENT,
        "body": json.dumps({"designation": "ccd", "timeline": "ytd", "filters": {}}),
    }
    response = handler.handler(event, None)
    assert response["statusCode"] == 400
    assert "viewId" in _body(response)["message"]


def test_handler_fetch_charts_rejects_get():
    event = {**FETCH_CHARTS_EVENT, "httpMethod": "GET", "body": None}
    response = handler.handler(event, None)
    assert response["statusCode"] == 405


ADMIN_EVENT = {
    **EVENT,
    "httpMethod": "GET",
    "path": "/jw-api/secure-data/admin",
}


def test_handler_admin_returns_admin_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("FEATURE_FLAGS_OVERRIDE_FILE", str(tmp_path / "feature_flags.local.json"))
    monkeypatch.delenv("ENABLE_AI_CHAT", raising=False)
    response = handler.handler(ADMIN_EVENT, None)
    assert response["statusCode"] == 200
    body = _body(response)
    assert body["message"] == "Admin area"
    assert body["enableAiChat"] is False
    assert body["features"]["aiChat"] is False
    assert body["lanId"] == "TESTUSER01"
    assert body["roles"] == ["user"]
    assert body["servedAt"]


def test_handler_admin_rejects_post():
    event = {**ADMIN_EVENT, "httpMethod": "POST"}
    response = handler.handler(event, None)
    assert response["statusCode"] == 405


AI_CHAT_EVENT = {
    **EVENT,
    "httpMethod": "POST",
    "path": "/jw-api/secure-data/ai-chat",
    "body": json.dumps({"prompt": "show doughnut of claims by region"}),
}


def test_handler_ai_chat_returns_chart_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("FEATURE_FLAGS_OVERRIDE_FILE", str(tmp_path / "feature_flags.local.json"))
    monkeypatch.setenv("ENABLE_AI_CHAT", "true")
    import feature_flags

    feature_flags.update_feature_flags({"aiChat": True})

    response = handler.handler(AI_CHAT_EVENT, None)
    assert response["statusCode"] == 200
    body = _body(response)
    assert body["responseType"] == "chart"
    assert body["chartType"] == "doughnut"
    assert body["labels"]
    assert body["data"]
    assert "claim_fact" in body["meta"]["sql"]


def test_handler_ai_chat_requires_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("FEATURE_FLAGS_OVERRIDE_FILE", str(tmp_path / "feature_flags.local.json"))
    monkeypatch.setenv("ENABLE_AI_CHAT", "true")
    import feature_flags

    feature_flags.update_feature_flags({"aiChat": True})

    event = {**AI_CHAT_EVENT, "body": json.dumps({})}
    response = handler.handler(event, None)
    assert response["statusCode"] == 400
    assert "prompt" in _body(response)["message"]
