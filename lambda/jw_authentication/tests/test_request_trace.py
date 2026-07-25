import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

AUTH_DIR = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("jw_log", AUTH_DIR / "jw_log.py")
jw_log = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(jw_log)


class _Context:
    aws_request_id = "aws-req-123"


def _capture_emit(monkeypatch):
    lines = []
    monkeypatch.setattr(jw_log, "emit", lambda evt, **fields: lines.append((evt, fields)))
    return lines


def test_http_request_lifecycle(monkeypatch):
    lines = _capture_emit(monkeypatch)
    event = {
        "httpMethod": "GET",
        "path": "/jw-api/token-auth",
        "headers": {"Authorization": "Bearer secret", "Origin": "http://localhost:4200"},
        "queryStringParameters": {"redirect": "true"},
        "requestContext": {"requestId": "gw-req-456", "stage": "dev"},
    }
    req = jw_log.Request("jw_authentication", event, _Context())
    response = req.complete({"statusCode": 200, "body": "{}"})

    assert response["statusCode"] == 200
    assert len(lines) == 2
    begin_evt, begin = lines[0]
    end_evt, end = lines[1]
    assert begin_evt == "request.begin"
    assert end_evt == "request.end"
    assert begin["rid"] == "gw-req-456"
    assert end["rid"] == "gw-req-456"
    assert begin["op"] == "validate_token"
    assert end["status"] == 200
    assert "ms" in end


def test_authorizer_failure(monkeypatch):
    lines = _capture_emit(monkeypatch)
    req = jw_log.Request(
        "jw_authorization",
        {"authorizationToken": "", "methodArn": "arn:..."},
        _Context(),
    )
    req.fail_authorizer(ValueError("bad signature"))

    assert lines[0][0] == "authorizer.begin"
    assert lines[1][0] == "authorizer.fail"
    assert "bad signature" in lines[1][1]["err"]


def test_redirect_response_strips_secrets():
    fields = jw_log._response_fields({
        "statusCode": 302,
        "headers": {"Location": "http://localhost:4200/authorize#accessToken=secret"},
        "body": "",
    })
    assert fields["redirect"] is True
    assert "accessToken" not in fields["redirectTo"]
    assert fields["redirectTo"] == "http://localhost:4200/authorize"


def test_classify_access_denied():
    from botocore.exceptions import ClientError

    exc = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "not authorized"}},
        "GetSecretValue",
    )
    detail = jw_log.classify_error("secretsmanager", exc)
    assert detail["reason"] == "missing_iam_permission"
    assert "GetSecretValue" in detail["hint"]
