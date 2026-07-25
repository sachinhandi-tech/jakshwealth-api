"""Okta bypass for pre-onboarding environments (``JW_BYPASS_OKTA_AUTH``)."""

from __future__ import annotations

import base64
import os
import time

TOKEN_PREFIX = "jw-bypass."
DEFAULT_LAN_ID = "DEVUSER01"
DEFAULT_SESSION_HOURS = 8
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


def bypass_lan_id() -> str:
    return (os.environ.get("JW_BYPASS_OKTA_LAN_ID") or DEFAULT_LAN_ID).strip()


def bypass_groups() -> list[str]:
    groups = []
    for key in ("USER_GG", "ADMIN_GG"):
        value = os.environ.get(key, "").strip()
        if value:
            groups.append(value)
    return groups


def issue_access_token(lan_id: str | None = None, groups: list[str] | None = None) -> str:
    lan_id = lan_id or bypass_lan_id()
    groups = groups if groups is not None else bypass_groups()
    expires_at = int(time.time()) + DEFAULT_SESSION_HOURS * 3600
    payload = f"{lan_id}|{','.join(groups)}|{expires_at}"
    encoded = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{TOKEN_PREFIX}{encoded}"


def parse_access_token(token: str) -> dict | None:
    if not token or not token.startswith(TOKEN_PREFIX) or not bypass_okta_enabled():
        return None
    encoded = token[len(TOKEN_PREFIX) :]
    padding = "=" * (-len(encoded) % 4)
    try:
        payload = base64.urlsafe_b64decode(encoded + padding).decode()
    except (ValueError, UnicodeDecodeError):
        return None
    parts = payload.split("|", 2)
    if len(parts) != 3:
        return None
    lan_id, groups_raw, expires_raw = parts
    try:
        expires_at = int(expires_raw)
    except ValueError:
        return None
    if expires_at < int(time.time()):
        return None
    groups = [group for group in groups_raw.split(",") if group]
    return {"lanId": lan_id, "groups": groups, "exp": expires_at}


def claims_dict(token: str) -> dict | None:
    """Map a bypass token to Okta-like claims for shared ``okta`` helpers."""
    parsed = parse_access_token(strip_bearer_prefix(token))
    if not parsed:
        return None
    return {
        "samAccountName": parsed["lanId"],
        "groups": parsed["groups"],
        "exp": parsed["exp"],
    }


def strip_bearer_prefix(value: str) -> str:
    value = (value or "").strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return value
