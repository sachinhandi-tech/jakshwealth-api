import cors


def test_resolve_frontend_base_uses_redirect_uri_in_dev(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:4200")
    event = {
        "queryStringParameters": {
            "redirect_uri": "https://jw-ui-dev.aws.example.com",
        }
    }
    assert (
        cors.resolve_frontend_base(event)
        == "https://jw-ui-dev.aws.example.com"
    )


def test_resolve_frontend_base_ignores_localhost_frontend_url_in_dev(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:4200")
    assert (
        cors.resolve_frontend_base({})
        == "https://jw-ui-dev.aws.example.com"
    )


def test_resolve_frontend_base_prefers_origin_header(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("FRONTEND_URL", "http://localhost:4200")
    event = {
        "headers": {"Origin": "https://jw-ui-dev.aws.example.com"},
        "queryStringParameters": {"redirect_uri": "https://other.example.com"},
    }
    assert (
        cors.resolve_frontend_base(event)
        == "https://jw-ui-dev.aws.example.com"
    )


def test_resolve_frontend_base_rejects_unlisted_redirect_uri(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    event = {"queryStringParameters": {"redirect_uri": "https://evil.example.com"}}
    assert (
        cors.resolve_frontend_base(event)
        == "https://jw-ui-dev.aws.example.com"
    )
