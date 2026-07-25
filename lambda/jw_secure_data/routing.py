"""Shared secure-data routing utilities."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import responses
from request_trace import RequestTrace

ROUTE_PREFIX = "jw-api/secure-data"

FeatureHandler = Callable[[dict, RequestTrace, dict[str, Any], str], dict]


@dataclass(frozen=True)
class FeatureRoute:
    """Single secure-data subroute owned by a feature module."""

    path: str
    methods: frozenset[str]
    handle: FeatureHandler

    def dispatch(
        self,
        event: dict,
        trace: RequestTrace,
        authorizer: dict[str, Any],
        method: str,
    ) -> dict:
        if method not in self.methods:
            allowed = ", ".join(sorted(self.methods))
            return trace.complete(
                responses.method_not_allowed(f"{allowed} required for {self.path}")
            )
        return self.handle(event, trace, authorizer, method)


def normalize_path(path: str | None) -> str:
    return (path or "").strip("/")


def route_suffix(path: str | None) -> str:
    normalized = normalize_path(path)
    if normalized == ROUTE_PREFIX:
        return ""
    prefix = f"{ROUTE_PREFIX}/"
    if normalized.startswith(prefix):
        return normalized[len(prefix):]
    return ""


def parse_json_body(event: dict | None) -> dict[str, Any]:
    raw = (event or {}).get("body")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def dispatch_feature_routes(
    routes: tuple[FeatureRoute, ...],
    *,
    suffix: str,
    event: dict,
    trace: RequestTrace,
    authorizer: dict[str, Any],
    method: str,
) -> dict | None:
    """Return a response when a feature route matches; otherwise None."""
    for route in routes:
        if suffix == route.path:
            return route.dispatch(event, trace, authorizer, method)
    return None
