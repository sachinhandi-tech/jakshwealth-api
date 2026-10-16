"""Admin secure-data feature."""

from __future__ import annotations

from typing import Any

import responses
from caller_context import lan_id_from_authorizer, roles_from_authorizer
from features.admin import service
from request_trace import RequestTrace
from routing import FeatureRoute, parse_json_body


def handle_admin(event, trace: RequestTrace, authorizer: dict[str, Any], method: str) -> dict:
    del method
    payload = service.build_admin_payload(authorizer)
    payload["lanId"] = lan_id_from_authorizer(authorizer)
    payload["roles"] = roles_from_authorizer(authorizer)
    return trace.complete(responses.ok(payload))


def handle_features(event, trace: RequestTrace, authorizer: dict[str, Any], method: str) -> dict:
    del authorizer, method
    body = parse_json_body(event)
    try:
        payload = service.update_features(body)
    except ValueError as exc:
        return trace.complete(responses.bad_request(str(exc)))
    except RuntimeError as exc:
        return trace.complete(responses.bad_request(str(exc)))

    return trace.complete(responses.ok(payload))


ROUTE = FeatureRoute(path="admin", methods=frozenset({"GET"}), handle=handle_admin)
FEATURES_ROUTE = FeatureRoute(
    path="admin/features",
    methods=frozenset({"POST"}),
    handle=handle_features,
)
