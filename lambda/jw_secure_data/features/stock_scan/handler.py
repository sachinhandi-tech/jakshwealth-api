"""Stock scan secure-data feature."""

from __future__ import annotations

from typing import Any

import responses
from features.stock_scan import service
from routing import FeatureRoute, parse_json_body
from request_trace import RequestTrace


def _handle_scan(event, trace: RequestTrace, authorizer: dict[str, Any], method: str) -> dict:
    payload = parse_json_body(event)
    try:
        body = service.run_scan(payload)
    except ValueError as exc:
        return trace.complete(responses.bad_request(str(exc)))
    except FileNotFoundError as exc:
        return trace.complete(responses.bad_request(str(exc)))
    return trace.complete(responses.ok(body))


def _handle_universe(event, trace: RequestTrace, authorizer: dict[str, Any], method: str) -> dict:
    try:
        body = service.universe_info()
    except (FileNotFoundError, ValueError) as exc:
        return trace.complete(responses.bad_request(str(exc)))
    return trace.complete(responses.ok(body))


ROUTE = FeatureRoute(path="stock-scan", methods=frozenset({"POST"}), handle=_handle_scan)
UNIVERSE_ROUTE = FeatureRoute(path="stock-universe", methods=frozenset({"GET"}), handle=_handle_universe)
