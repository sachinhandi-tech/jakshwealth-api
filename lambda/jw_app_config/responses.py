"""API Gateway (proxy integration) HTTP response builders."""

from __future__ import annotations

import json
from http import HTTPStatus

import cors

_ALLOW_METHODS = "GET,OPTIONS"


def bind_request_origin(event) -> None:
    cors.bind_request_origin(event)


def _response(status: HTTPStatus, body) -> dict:
    body_text = body if isinstance(body, str) else json.dumps(body, default=str)
    return {
        "isBase64Encoded": False,
        "statusCode": int(status),
        "headers": cors.cors_headers(_ALLOW_METHODS),
        "body": body_text,
    }


def ok(body) -> dict:
    return _response(HTTPStatus.OK, body)


def method_not_allowed(message: str) -> dict:
    return _response(HTTPStatus.METHOD_NOT_ALLOWED, {"message": message})


def options() -> dict:
    return _response(HTTPStatus.OK, {"message": "ok"})
