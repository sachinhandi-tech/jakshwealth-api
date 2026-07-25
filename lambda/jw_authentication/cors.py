"""CORS — allowed origins from FRONTEND_URL and JW_CORS_ALLOWED_ORIGINS."""

from __future__ import annotations

import os
from urllib.parse import urlparse

ALLOW_HEADERS = "Authorization, Content-Type, cache-control, auth_code, refresh_token"

_LOCAL_DEV_ORIGIN_URLS = (
    "http://localhost:4200",
    "http://127.0.0.1:4200",
)

# Default deployed UI origin when FRONTEND_URL is unset (local override only).
def _default_ui_origin() -> str:
    env = _environment()
    if env in ("", "local"):
        return ""
    return f"https://jw-ui-{env}.aws.example.com"


def _environment() -> str:
    return (os.environ.get("ENVIRONMENT") or "local").strip().lower()


def _is_local_env() -> bool:
    return _environment() == "local"


def _local_dev_origins() -> frozenset[str]:
    if not _is_local_env():
        return frozenset()
    return frozenset(_LOCAL_DEV_ORIGIN_URLS)


def configured_origins() -> frozenset[str]:
    origins: set[str] = set(_local_dev_origins())
    frontend = (os.environ.get("FRONTEND_URL") or "").strip().rstrip("/")
    if frontend:
        origins.add(frontend)
    default_ui = _default_ui_origin()
    if default_ui:
        origins.add(default_ui)
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


def _header_value(event, name: str) -> str:
    headers = (event or {}).get("headers") or {}
    target = name.lower().replace("_", "-")
    for key, value in headers.items():
        if isinstance(key, str) and key.lower().replace("_", "-") == target and value:
            return str(value).strip()
    return ""


def _query_value(event, name: str) -> str:
    return str(((event or {}).get("queryStringParameters") or {}).get(name) or "").strip()


def _origin_from_referer(referer: str) -> str:
    if not referer:
        return ""
    parsed = urlparse(referer)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    return ""


def _is_local_origin(origin: str) -> bool:
    if not origin:
        return False
    normalized = origin.rstrip("/")
    if normalized in _LOCAL_DEV_ORIGIN_URLS:
        return True
    return normalized.startswith("http://localhost:") or normalized.startswith("http://127.0.0.1:")


def _allowed_origin(origin: str, allowed: frozenset[str]) -> str:
    normalized = origin.rstrip("/")
    if normalized and (not allowed or normalized in allowed):
        return normalized
    return ""


def resolve_frontend_base(event) -> str:
    """Resolve the SPA origin for auth redirects (bypass / token exchange).

    Full-page navigations to ``token-auth`` omit ``Origin``; use ``redirect_uri``,
    ``Referer``, ``FRONTEND_URL``, or the deployed UI host for the current env.
    """
    allowed = configured_origins()

    origin = _allowed_origin(_header_value(event, "origin"), allowed)
    if origin:
        return origin

    redirect_uri = _allowed_origin(_query_value(event, "redirect_uri"), allowed)
    if redirect_uri:
        return redirect_uri

    referer_origin = _allowed_origin(_origin_from_referer(_header_value(event, "referer")), allowed)
    if referer_origin:
        return referer_origin

    frontend = (os.environ.get("FRONTEND_URL") or "").strip().rstrip("/")
    if frontend:
        if not _is_local_env() and _is_local_origin(frontend):
            pass
        else:
            chosen = _allowed_origin(frontend, allowed)
            if chosen:
                return chosen

    default_ui = _default_ui_origin()
    if default_ui:
        return default_ui

    return _LOCAL_DEV_ORIGIN_URLS[0]


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
