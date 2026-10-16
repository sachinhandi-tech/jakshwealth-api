"""API Gateway (proxy integration) HTTP response builders."""

from __future__ import annotations

import json
from http import HTTPStatus

import cors

_ALLOW_METHODS = "GET,POST,OPTIONS"


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


def bad_request(message: str | dict) -> dict:
    body = message if isinstance(message, dict) else {"message": message}
    return _response(HTTPStatus.BAD_REQUEST, body)


def method_not_allowed(message: str) -> dict:
    return _response(HTTPStatus.METHOD_NOT_ALLOWED, {"message": message})


def not_found(message: str | dict) -> dict:
    body = message if isinstance(message, dict) else {"message": message}
    return _response(HTTPStatus.NOT_FOUND, body)


def options() -> dict:
    return _response(HTTPStatus.OK, {"message": "ok"})


def accepted(body) -> dict:
    return _response(HTTPStatus.ACCEPTED, body)
