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


@patch.dict(
    "os.environ",
    {
        "JW_BYPASS_OKTA_AUTH": "true",
        "JW_BYPASS_OKTA_LAN_ID": "TESTUSER01",
        "USER_GG": "TEST_USER_GROUP",
        "ADMIN_GG": "TEST_ADMIN_GROUP",
    },
    clear=False,
)
def test_bypass_token_is_allowed():
    import bypass_auth

    token = bypass_auth.issue_access_token()
    policy = handler.handler({"authorizationToken": token, "methodArn": ARN}, None)
    assert policy["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert policy["context"]["lanId"] == "TESTUSER01"
    assert policy["context"]["roles"] == "user,admin"


@patch.dict(
    "os.environ",
    {
        "JW_BYPASS_OKTA_AUTH": "true",
        "USER_GG": "TEST_USER_GROUP",
        "ADMIN_GG": "TEST_ADMIN_GROUP",
    },
    clear=False,
)
def test_bypass_token_is_denied_without_matching_groups():
    import bypass_auth

    token = bypass_auth.issue_access_token("TESTUSER01", ["OTHER_GROUP"])
    policy = handler.handler({"authorizationToken": token, "methodArn": ARN}, None)
    assert policy["policyDocument"]["Statement"][0]["Effect"] == "Deny"
    assert "context" not in policy
