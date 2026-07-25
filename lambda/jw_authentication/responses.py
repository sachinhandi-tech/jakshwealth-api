"""API Gateway (proxy integration) HTTP response builders."""

from __future__ import annotations

import json
from http import HTTPStatus

import cors

_ALLOW_METHODS = "GET,OPTIONS"


def bind_request_origin(event) -> None:
    cors.bind_request_origin(event)


def _response(status: HTTPStatus, body) -> dict:
    return {
        "statusCode": int(status),
        "headers": {
            "Content-Type": "application/json",
            **cors.cors_headers(_ALLOW_METHODS, json_response=False),
        },
        "body": body if isinstance(body, str) else json.dumps(body, default=str),
    }


def ok(body) -> dict:
    return _response(HTTPStatus.OK, body)


def bad_request(message: str) -> dict:
    return _response(HTTPStatus.BAD_REQUEST, {"message": message})


def unauthorized(message: str) -> dict:
    return _response(HTTPStatus.UNAUTHORIZED, {"message": message})


def method_not_allowed(message: str) -> dict:
    return _response(HTTPStatus.METHOD_NOT_ALLOWED, {"message": message})


def error(message: str) -> dict:
    return _response(HTTPStatus.INTERNAL_SERVER_ERROR, {"message": message})


def options() -> dict:
    return _response(HTTPStatus.OK, {"message": "ok"})


def redirect(location: str, status: HTTPStatus = HTTPStatus.FOUND) -> dict:
    return {
        "statusCode": int(status),
        "headers": {"Location": location, **cors.cors_headers(_ALLOW_METHODS, json_response=False)},
        "body": "",
    }
