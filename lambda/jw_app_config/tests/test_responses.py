import cors
import responses


def test_ok_response_echoes_allowed_local_origin(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    responses.bind_request_origin(
        {"headers": {"Origin": "http://localhost:4200", "origin": "http://localhost:4200"}}
    )
    response = responses.ok({"appName": "JakshWealth"})

    assert response["headers"]["Access-Control-Allow-Origin"] == "http://localhost:4200"
    assert response["headers"]["Vary"] == "Origin"


def test_ok_response_uses_frontend_url_when_origin_missing(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("FRONTEND_URL", "https://dev-jw.example.com")
    cors.clear_request_origin()
    response = responses.ok({"appName": "JakshWealth"})

    assert response["headers"]["Access-Control-Allow-Origin"] == "https://dev-jw.example.com"


def test_extra_origins_from_env(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("FRONTEND_URL", "https://dev-jw.example.com")
    monkeypatch.setenv(
        "SSA_CORS_ALLOWED_ORIGINS",
        "https://d111.cloudfront.net,https://custom.example.com",
    )
    responses.bind_request_origin(
        {"headers": {"Origin": "https://d111.cloudfront.net"}}
    )
    response = responses.ok({})

    assert response["headers"]["Access-Control-Allow-Origin"] == "https://d111.cloudfront.net"
