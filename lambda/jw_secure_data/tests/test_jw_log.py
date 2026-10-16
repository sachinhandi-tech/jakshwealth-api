import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

SECURE_DIR = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("jw_log", SECURE_DIR / "jw_log.py")
jw_log = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(jw_log)

_config_spec = importlib.util.spec_from_file_location("config", SECURE_DIR / "config.py")
config = importlib.util.module_from_spec(_config_spec)
assert _config_spec.loader is not None
_config_spec.loader.exec_module(config)


def test_call_external_raises_on_access_denied(monkeypatch):
    lines = []
    monkeypatch.setattr(jw_log, "emit", lambda evt, **fields: lines.append((evt, fields)))

    def _fail():
        raise ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}},
            "GetSecretValue",
        )

    with pytest.raises(jw_log.ExternalServiceError) as exc_info:
        jw_log.call_external("secretsmanager", "GetSecretValue", _fail, secretName="dev/jakshwealth/config")

    assert exc_info.value.reason == "missing_iam_permission"
    assert lines[-1][0] == "external.fail"
    assert lines[-1][1]["reason"] == "missing_iam_permission"
    assert "hint" in lines[-1][1]


@patch("boto3.client")
def test_fetch_secret_uses_timeouts(mock_client, monkeypatch):
    monkeypatch.setenv("AWS_REGION", "ap-south-2")
    monkeypatch.setattr(jw_log, "emit", lambda *args, **kwargs: None)
    client = MagicMock()
    client.get_secret_value.return_value = {"SecretString": '{"OKTA_URL":"https://example"}'}
    mock_client.return_value = client

    result = config._fetch_secret("dev/jakshwealth/config")
    assert result["OKTA_URL"] == "https://example"
    _, kwargs = mock_client.call_args
    assert kwargs["config"].connect_timeout == 5
    assert kwargs["config"].read_timeout == 10
