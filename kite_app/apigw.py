"""API Gateway path cleanup for the Kite Lambda."""

from __future__ import annotations

_PREFIX = "/jw-api/kite"


def normalize_path(path: str) -> str:
    """Turn /jw-api/kite/api/kite/session into /api/kite/session."""
    value = path or "/"
    stage_prefix = "/dev" + _PREFIX
    for prefix in (stage_prefix, _PREFIX):
        if value == prefix or value.startswith(prefix + "/"):
            rest = value[len(prefix) :]
            return rest or "/"
    return value


def normalize_event(event: dict) -> dict:
    if not isinstance(event, dict):
        return event
    for key in ("path", "rawPath"):
        if isinstance(event.get(key), str):
            event[key] = normalize_path(event[key])
    context = event.get("requestContext")
    if isinstance(context, dict):
        http = context.get("http")
        if isinstance(http, dict) and isinstance(http.get("path"), str):
            http["path"] = normalize_path(http["path"])
    return event
