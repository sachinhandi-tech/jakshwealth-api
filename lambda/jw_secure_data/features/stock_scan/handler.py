"""Stock scan secure-data feature."""

from __future__ import annotations

from typing import Any

import responses
from features.stock_scan import async_service, service
from routing import FeatureRoute, parse_json_body, route_suffix
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


def _handle_async_scan(event, trace: RequestTrace, authorizer: dict[str, Any], method: str) -> dict:
    payload = parse_json_body(event)
    try:
        body = async_service.start_async_scan(payload)
    except ValueError as exc:
        return trace.complete(responses.bad_request(str(exc)))
    except FileNotFoundError as exc:
        return trace.complete(responses.bad_request(str(exc)))
    return trace.complete(responses.accepted(body))


def _handle_job_status(event, trace: RequestTrace, authorizer: dict[str, Any], method: str) -> dict:
    suffix = route_suffix((event or {}).get("path"))
    job_id = suffix.removeprefix("stock-scan/jobs/").strip("/")
    if not job_id or "/" in job_id:
        return trace.complete(responses.bad_request("Invalid job id"))

    job = async_service.get_job_status(job_id)
    if job is None:
        return trace.complete(responses.not_found("Scan job not found"))
    return trace.complete(responses.ok(job))


def _query_param(event: dict, name: str) -> str | None:
    params = (event or {}).get("queryStringParameters") or {}
    value = params.get(name)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _handle_universe(event, trace: RequestTrace, authorizer: dict[str, Any], method: str) -> dict:
    segment = _query_param(event, "segment")
    try:
        body = service.universe_info(segment)
    except (FileNotFoundError, ValueError) as exc:
        return trace.complete(responses.bad_request(str(exc)))
    return trace.complete(responses.ok(body))


ROUTE = FeatureRoute(path="stock-scan", methods=frozenset({"POST"}), handle=_handle_scan)
ASYNC_ROUTE = FeatureRoute(path="stock-scan/async", methods=frozenset({"POST"}), handle=_handle_async_scan)
JOB_ROUTE = FeatureRoute(
    path="stock-scan/jobs",
    path_prefix="stock-scan/jobs/",
    methods=frozenset({"GET"}),
    handle=_handle_job_status,
)
UNIVERSE_ROUTE = FeatureRoute(path="stock-universe", methods=frozenset({"GET"}), handle=_handle_universe)
