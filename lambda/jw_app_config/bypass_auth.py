"""Okta bypass flag for ``jw_app_config`` (pre-onboarding environments)."""

from __future__ import annotations

import os

_BYPASS_ENVIRONMENTS = frozenset({"local", "dev"})


def bypass_okta_enabled() -> bool:
    flag = str(os.environ.get("JW_BYPASS_OKTA_AUTH", "")).strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if not flag:
        return False
    env = (os.environ.get("ENVIRONMENT") or "local").strip().lower()
    return env in _BYPASS_ENVIRONMENTS
