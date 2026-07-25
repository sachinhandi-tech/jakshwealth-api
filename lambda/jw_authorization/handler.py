"""API Gateway TOKEN authorizer for JakshWealth."""

from __future__ import annotations

import authorization_debug as debug
import config
import okta
from roles import resolve_roles
from jw_log import Request

config.load_config()
_SERVICE = "jw_authorization"


def handler(event, context):
    req = Request(_SERVICE, event, context)
    token = (event or {}).get("authorizationToken")
    method_arn = (event or {}).get("methodArn")
    if not token:
        req.fail_authorizer(Exception("Unauthorized - missing token"))
        raise Exception("Unauthorized")

    try:
        token_claims = okta.claims(token)
    except Exception as exc:
        req.fail_authorizer(exc)
        raise Exception("Unauthorized") from exc

    caller_groups = okta.groups(token_claims)
    allowed_groups = config.required_global_groups()
    matched_groups = sorted(set(caller_groups) & set(allowed_groups))
    allowed = bool(matched_groups)
    principal = okta.lan_id(token_claims) or "unknown"
    roles = resolve_roles(caller_groups)
    authorizer_context = {"lanId": principal, "roles": ",".join(roles)}

    membership = debug.membership_summary(caller_groups)
    req.note(
        principal=principal,
        allowed=allowed,
        matchedGroups=matched_groups,
        roles=roles,
        **membership,
    )
    return req.complete_authorizer(
        _policy(
            principal if allowed else "denied",
            "Allow" if allowed else "Deny",
            method_arn,
            authorizer_context if allowed else None,
        )
    )


def _policy(principal_id, effect, resource, authorizer_context=None):
    result = {
        "principalId": principal_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {"Action": "execute-api:Invoke", "Effect": effect, "Resource": resource}
            ],
        },
    }
    if effect == "Allow" and authorizer_context:
        result["context"] = {key: str(value) for key, value in authorizer_context.items()}
    return result
