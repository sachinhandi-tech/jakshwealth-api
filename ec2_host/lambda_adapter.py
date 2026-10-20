"""Turn one HTTP request into the event shape the Lambda handlers already expect."""

from __future__ import annotations

import base64
from urllib.parse import parse_qs, urlsplit


def build_lambda_event(method: str, target: str, headers: dict, body: bytes) -> dict:
    parsed = urlsplit(target)
    query = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
    header_map = {str(key): str(value) for key, value in headers.items()}
    text = body.decode("utf-8") if body else None
    return {
        "httpMethod": method.upper(),
        "path": parsed.path or "/",
        "headers": header_map,
        "queryStringParameters": query or None,
        "body": text,
        "isBase64Encoded": False,
        "requestContext": {"authorizer": {}},
    }


def apply_lambda_result(handler, event: dict) -> tuple[int, list[tuple[str, str]], bytes]:
    result = handler(event, None)
    if not isinstance(result, dict):
        return 500, [("Content-Type", "application/json")], b'{"message":"The service returned an empty result."}'
    status = int(result.get("statusCode") or 500)
    pairs = []
    for key, value in (result.get("headers") or {}).items():
        if value is not None:
            pairs.append((str(key), str(value)))
    raw = result.get("body") or ""
    if result.get("isBase64Encoded"):
        payload = base64.b64decode(raw)
    elif isinstance(raw, str):
        payload = raw.encode("utf-8")
    else:
        payload = bytes(raw)
    return status, pairs, payload
