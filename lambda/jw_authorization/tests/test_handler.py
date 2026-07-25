import importlib.util
from pathlib import Path
from unittest.mock import patch

AUTHORIZATION_DIR = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "jw_authorization_handler", AUTHORIZATION_DIR / "handler.py"
)
handler = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(handler)

ARN = "arn:aws:execute-api:us-east-1:123:api/dev/GET/secure-data"


def _effect(policy):
    return policy["policyDocument"]["Statement"][0]["Effect"]


def _mock_token_claims(lan_id="TESTUSER01", groups=None):
    groups = groups or ["TEST_USER_GROUP"]
    return {"samAccountName": lan_id, "apigroups": ",".join(groups)}


def test_missing_token_is_unauthorized():
    try:
        handler.handler({"methodArn": ARN}, None)
    except Exception as exc:
        assert "Unauthorized" in str(exc)
    else:
        raise AssertionError("expected Unauthorized exception")


@patch.object(handler, "okta")
def test_user_group_member_is_allowed(mock_okta):
    mock_okta.claims.return_value = _mock_token_claims(groups=["TEST_USER_GROUP"])
    mock_okta.groups.return_value = ["TEST_USER_GROUP"]
    mock_okta.lan_id.return_value = "TESTUSER01"

    policy = handler.handler({"authorizationToken": "Bearer token", "methodArn": ARN}, None)
    assert _effect(policy) == "Allow"
    assert policy["principalId"] == "TESTUSER01"
    assert policy["context"]["lanId"] == "TESTUSER01"
    assert policy["context"]["roles"] == "user"


@patch.object(handler, "okta")
def test_admin_group_member_is_allowed(mock_okta):
    mock_okta.claims.return_value = _mock_token_claims(groups=["TEST_ADMIN_GROUP"])
    mock_okta.groups.return_value = ["TEST_ADMIN_GROUP"]
    mock_okta.lan_id.return_value = "TESTUSER01"

    policy = handler.handler({"authorizationToken": "Bearer token", "methodArn": ARN}, None)
    assert _effect(policy) == "Allow"
    assert policy["context"]["roles"] == "admin"


@patch.object(handler, "okta")
def test_user_and_admin_roles_in_context(mock_okta):
    groups = ["TEST_USER_GROUP", "TEST_ADMIN_GROUP"]
    mock_okta.claims.return_value = _mock_token_claims(groups=groups)
    mock_okta.groups.return_value = groups
    mock_okta.lan_id.return_value = "TESTUSER01"

    policy = handler.handler({"authorizationToken": "Bearer token", "methodArn": ARN}, None)
    assert _effect(policy) == "Allow"
    assert policy["context"]["roles"] == "user,admin"


@patch.object(handler, "okta")
def test_non_member_is_denied(mock_okta):
    mock_okta.claims.return_value = _mock_token_claims(groups=["SOME_OTHER_GROUP"])
    mock_okta.groups.return_value = ["SOME_OTHER_GROUP"]
    mock_okta.lan_id.return_value = "TESTUSER01"

    policy = handler.handler({"authorizationToken": "Bearer token", "methodArn": ARN}, None)
    assert _effect(policy) == "Deny"
    assert "context" not in policy


@patch.object(handler, "okta")
def test_invalid_token_is_unauthorized(mock_okta):
    mock_okta.claims.side_effect = ValueError("bad signature")
    try:
        handler.handler({"authorizationToken": "Bearer bad", "methodArn": ARN}, None)
    except Exception as exc:
        assert "Unauthorized" in str(exc)
    else:
        raise AssertionError("expected Unauthorized exception")
