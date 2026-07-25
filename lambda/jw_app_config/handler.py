"""Public application configuration endpoint (``/jw-api/app-config``)."""

from __future__ import annotations

import json
import os

import bypass_auth
import config
import feature_flags
import responses
from jw_log import Request, emit

config.load_config()
_SERVICE = "jw_app_config"


def _features():
    try:
        return feature_flags.load_feature_flags()
    except ValueError as exc:
        emit("config.warn", lvl="ERROR", err=str(exc))
        return feature_flags.default_feature_flags()


def handler(event, context):
    req = Request(_SERVICE, event, context)
    responses.bind_request_origin(event)
    method = (event or {}).get("httpMethod")
    if method == "OPTIONS":
        return req.complete(responses.options())
    if method != "GET":
        return req.complete(responses.method_not_allowed(f"{method} not supported"))

    return req.complete(
        responses.ok(
            {
                "appName": "JakshWealth",
                "version": os.environ.get("APP_VERSION", "0.1.0"),
                "environment": (os.environ.get("ENVIRONMENT") or "dev").strip().lower(),
                "features": _features(),
                "enableAiChat": feature_flags.can_manage_ai_chat(),
                "bypassOktaAuth": bypass_auth.bypass_okta_enabled(),
                "clientId": (os.environ.get("OKTA_CLIENT_ID") or "").strip(),
            }
        )
    )
