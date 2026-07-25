import time

import bypass_auth


def test_bypass_disabled_by_default(monkeypatch):
    monkeypatch.delenv("JW_BYPASS_OKTA_AUTH", raising=False)
    assert bypass_auth.bypass_okta_enabled() is False
    assert bypass_auth.parse_access_token("jw-bypass.anything") is None


def test_bypass_disabled_in_prod_even_when_flag_set(monkeypatch):
    monkeypatch.setenv("JW_BYPASS_OKTA_AUTH", "true")
    monkeypatch.setenv("ENVIRONMENT", "prod")
    assert bypass_auth.bypass_okta_enabled() is False


def test_bypass_enabled_in_dev(monkeypatch):
    monkeypatch.setenv("JW_BYPASS_OKTA_AUTH", "true")
    monkeypatch.setenv("ENVIRONMENT", "dev")
    assert bypass_auth.bypass_okta_enabled() is True


def test_issue_and_parse_round_trip(monkeypatch):
    monkeypatch.setenv("JW_BYPASS_OKTA_AUTH", "true")
    monkeypatch.setenv("USER_GG", "TEST_USER_GROUP")
    monkeypatch.setenv("ADMIN_GG", "TEST_ADMIN_GROUP")
    monkeypatch.setenv("JW_BYPASS_OKTA_LAN_ID", "TESTUSER01")

    token = bypass_auth.issue_access_token()
    parsed = bypass_auth.parse_access_token(token)
    assert parsed is not None
    assert parsed["lanId"] == "TESTUSER01"
    assert parsed["groups"] == ["TEST_USER_GROUP", "TEST_ADMIN_GROUP"]
    assert parsed["exp"] > int(time.time())


def test_expired_bypass_token_is_rejected(monkeypatch):
    monkeypatch.setenv("JW_BYPASS_OKTA_AUTH", "true")
    token = bypass_auth.issue_access_token("TESTUSER01", ["GROUP"])
    parsed = bypass_auth.parse_access_token(token)
    assert parsed is not None
    parsed["exp"] = int(time.time()) - 1
    # Rebuild expired token manually
    import base64

    payload = f"TESTUSER01|GROUP|{parsed['exp']}"
    encoded = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    expired = f"{bypass_auth.TOKEN_PREFIX}{encoded}"
    assert bypass_auth.parse_access_token(expired) is None
