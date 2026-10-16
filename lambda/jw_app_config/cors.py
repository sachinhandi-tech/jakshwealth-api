"""CORS — allowed origins from FRONTEND_URL and JW_CORS_ALLOWED_ORIGINS."""

from __future__ import annotations

import os

ALLOW_HEADERS = "Authorization, Content-Type, cache-control, auth_code, refresh_token"

_LOCAL_DEV_ORIGIN_URLS = (
    "http://localhost:4200",
    "http://127.0.0.1:4200",
)


def _is_local_env() -> bool:
    return (os.environ.get("ENVIRONMENT") or "local").strip().lower() == "local"


def _local_dev_origins() -> frozenset[str]:
    if not _is_local_env():
        return frozenset()
    return frozenset(_LOCAL_DEV_ORIGIN_URLS)


def configured_origins() -> frozenset[str]:
    origins: set[str] = set(_local_dev_origins())
    frontend = (os.environ.get("FRONTEND_URL") or "").strip().rstrip("/")
    if frontend:
        origins.add(frontend)
    extra = (os.environ.get("JW_CORS_ALLOWED_ORIGINS") or "").strip()
    if extra:
        for part in extra.split(","):
            origin = part.strip().rstrip("/")
            if origin:
                origins.add(origin)
    return frozenset(origins)


def bind_request_origin(event) -> None:
    headers = (event or {}).get("headers") or {}
    origin = ""
    for key, value in headers.items():
        if isinstance(key, str) and key.lower().replace("_", "-") == "origin" and value:
            origin = str(value).strip().rstrip("/")
            break
    if origin:
        os.environ["_REQUEST_ORIGIN"] = origin
    else:
        os.environ.pop("_REQUEST_ORIGIN", None)


def clear_request_origin() -> None:
    os.environ.pop("_REQUEST_ORIGIN", None)


def resolve_allow_origin() -> str:
    request_origin = (os.environ.get("_REQUEST_ORIGIN") or "").strip().rstrip("/")
    allowed = configured_origins()
    frontend = (os.environ.get("FRONTEND_URL") or "").strip().rstrip("/")

    if request_origin and request_origin in allowed:
        return request_origin
    if frontend:
        return frontend
    if _is_local_env() and request_origin:
        return request_origin
    return "*"


def cors_headers(allow_methods: str, *, json_response: bool = True) -> dict[str, str]:
    allow_origin = resolve_allow_origin()
    headers = {
        "Access-Control-Allow-Origin": allow_origin,
        "Access-Control-Allow-Headers": ALLOW_HEADERS,
        "Access-Control-Allow-Methods": allow_methods,
    }
    if json_response:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if allow_origin != "*":
        headers["Vary"] = "Origin"
    return headers
