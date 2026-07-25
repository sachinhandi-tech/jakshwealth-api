import importlib.util
from pathlib import Path
from unittest.mock import patch

AUTH_DIR = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "jw_authentication_handler", AUTH_DIR / "handler.py"
)
handler = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(handler)

EVENT = {
    "httpMethod": "GET",
    "headers": {"Origin": "http://localhost:4200"},
    "queryStringParameters": {"bypass": "true", "redirect": "true"},
}


@patch.dict("os.environ", {"JW_BYPASS_OKTA_AUTH": "true", "JW_BYPASS_OKTA_LAN_ID": "TESTUSER01", "USER_GG": "TEST_USER_GROUP"}, clear=False)
def test_bypass_login_redirects_to_authorize():
    response = handler.handler(EVENT, None)
    assert response["statusCode"] == 302
    location = response["headers"]["Location"]
    assert location.startswith("http://localhost:4200/authorize#")
    assert "accessToken=jw-bypass." in location
    assert "lanId=TESTUSER01" in location


@patch.dict("os.environ", {"JW_BYPASS_OKTA_AUTH": "false"}, clear=False)
def test_bypass_rejected_when_flag_disabled():
    response = handler.handler(EVENT, None)
    assert response["statusCode"] == 400


@patch.dict(
    "os.environ",
    {
        "JW_BYPASS_OKTA_AUTH": "true",
        "JW_BYPASS_OKTA_LAN_ID": "TESTUSER01",
        "USER_GG": "TEST_USER_GROUP",
        "ENVIRONMENT": "dev",
        "FRONTEND_URL": "http://localhost:4200",
    },
    clear=False,
)
def test_bypass_login_redirects_to_deployed_ui_without_origin():
    event = {
        "httpMethod": "GET",
        "headers": {},
        "queryStringParameters": {
            "bypass": "true",
            "redirect": "true",
            "redirect_uri": "https://app.jakshwealth.example.com",
        },
    }
    response = handler.handler(event, None)
    assert response["statusCode"] == 302
    location = response["headers"]["Location"]
    assert location.startswith("https://app.jakshwealth.example.com/authorize#")
    assert "accessToken=jw-bypass." in location
    assert "lanId=TESTUSER01" in location
