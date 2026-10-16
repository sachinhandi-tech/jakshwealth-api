"""Proof point chart secure-data feature."""

from __future__ import annotations

from typing import Any

import responses
from features.fetch_charts import service
from request_trace import RequestTrace
from routing import FeatureRoute, parse_json_body


def handle(event, trace: RequestTrace, authorizer: dict[str, Any], method: str) -> dict:
    payload = parse_json_body(event)
    view_id = str(payload.get("viewId") or "").strip()
    if not view_id:
        return trace.complete(responses.bad_request("viewId is required"))

    charts = service.build_charts(payload)
    return trace.complete(responses.ok({"charts": charts}))


ROUTE = FeatureRoute(path="fetch-charts", methods=frozenset({"POST"}), handle=handle)
