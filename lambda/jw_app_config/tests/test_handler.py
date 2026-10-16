import importlib.util
from pathlib import Path
from unittest.mock import patch

APP_CONFIG_DIR = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "jw_app_config_handler", APP_CONFIG_DIR / "handler.py"
)
handler = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(handler)

EVENT = {"httpMethod": "GET", "headers": {"Origin": "http://localhost:4200"}}


@patch.dict("os.environ", {"ENVIRONMENT": "dev"}, clear=False)
def test_app_config_returns_public_metadata():
    response = handler.handler(EVENT, None)
    assert response["statusCode"] == 200
    import json

    body = json.loads(response["body"])
    assert body["appName"] == "JakshWealth"
    assert body["environment"] == "dev"
    assert "features" in body


@patch.dict("os.environ", {"ENVIRONMENT": "dev"}, clear=False)
def test_app_config_exposes_ai_chat_feature_flag():
    response = handler.handler(EVENT, None)
    body = __import__("json").loads(response["body"])
    assert body["enableAiChat"] is False
    assert body["features"]["aiChat"] is False


@patch.dict(
    "os.environ",
    {"ENVIRONMENT": "dev", "ENABLE_AI_CHAT": "true"},
    clear=False,
)
def test_app_config_exposes_platform_ai_chat_gate_when_enabled():
    response = handler.handler(EVENT, None)
    body = __import__("json").loads(response["body"])
    assert body["enableAiChat"] is True
