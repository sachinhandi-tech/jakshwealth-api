"""Pretty-print authorizer context received by business Lambdas."""

from __future__ import annotations

import os

from jw_log import emit


def enabled() -> bool:
    return os.environ.get("JW_AUTH_DEBUG", "false").strip().lower() == "true"


def log_authorizer_context(
    service: str,
    *,
    raw_authorizer: dict,
    lan_id: str,
    roles: list[str],
    principal_id: str,
) -> None:
    if not enabled():
        return
    emit(
        "debug.authorizer",
        svc=service,
        rawAuthorizer=raw_authorizer or {},
        lanId=lan_id,
        roles=roles,
        principalId=principal_id,
    )
