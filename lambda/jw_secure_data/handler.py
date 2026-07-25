"""Protected demo endpoint (``/jw-api/secure-data``)."""

from __future__ import annotations

from datetime import datetime, timezone

import config
import responses
import secure_data_debug as debug
from caller_context import lan_id_from_authorizer, roles_from_authorizer
from features import FEATURE_ROUTES
from routing import dispatch_feature_routes, route_suffix
from jw_log import Request

config.load_config()
_SERVICE = "jw_secure_data"


def _secure_data_payload(event, authorizer: dict) -> dict:
    lan_id = lan_id_from_authorizer(authorizer)
    roles = roles_from_authorizer(authorizer)
    principal_id = authorizer.get("principalId", lan_id)
    return {
        "message": "You reached the protected secure-data endpoint.",
        "lanId": lan_id,
        "roles": roles,
        "principalId": principal_id,
        "servedAt": datetime.now(timezone.utc).isoformat(),
    }


def handler(event, context):
    req = Request(_SERVICE, event, context)
    responses.bind_request_origin(event)
    method = (event or {}).get("httpMethod")
    if method == "OPTIONS":
        return req.complete(responses.options())
    if method not in ("GET", "POST"):
        return req.complete(responses.method_not_allowed(f"{method} not supported"))

    authorizer = ((event or {}).get("requestContext") or {}).get("authorizer") or {}
    lan_id = lan_id_from_authorizer(authorizer)
    roles = roles_from_authorizer(authorizer)
    principal_id = authorizer.get("principalId", lan_id)
    suffix = route_suffix((event or {}).get("path"))

    req.note(lanId=lan_id, roles=roles, principalId=principal_id, route=suffix or "/")
    debug.log_authorizer_context(
        _SERVICE,
        raw_authorizer=authorizer,
        lan_id=lan_id,
        roles=roles,
        principal_id=principal_id,
    )

    feature_response = dispatch_feature_routes(
        FEATURE_ROUTES,
        suffix=suffix,
        event=event,
        trace=req,
        authorizer=authorizer,
        method=method,
    )
    if feature_response is not None:
        return feature_response

    if suffix:
        return req.complete(responses.bad_request(f"Unknown secure-data route: {suffix}"))

    return req.complete(responses.ok(_secure_data_payload(event, authorizer)))
