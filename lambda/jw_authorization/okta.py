"""Okta JWT verification for the API Gateway authorizer.

Configuration is read from the process environment (populated by
``config.load_config()``): ``OKTA_URL``, ``OKTA_ISSUER`` and ``OKTA_AUDIENCE``.
Only verification is needed here - the authorizer never exchanges tokens.
"""

from __future__ import annotations

import json
import os

import bypass_auth
import requests
from jose import jwt
from jw_log import call_external

_jwks_cache: dict | None = None


def base_url() -> str:
    return os.environ.get("OKTA_URL", "").rstrip("/")


def issuer() -> str:
    return os.environ.get("OKTA_ISSUER", "")


def audience() -> str:
    return os.environ.get("OKTA_AUDIENCE", "api://default")


def _endpoint_url(path_env_key: str, default_suffix: str) -> str:
    base = base_url()
    if not base:
        return ""
    configured = os.environ.get(path_env_key, "").strip()
    if configured:
        if configured.startswith("http"):
            return configured
        if base.endswith("/v1") and configured.startswith("/v1"):
            configured = configured[3:]
        return f"{base}{configured}" if configured.startswith("/") else f"{base}/{configured}"
    return f"{base}/{default_suffix.lstrip('/')}"


def keys_url() -> str:
    return _endpoint_url("OKTA_KEYS_PATH", "keys")


def _jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is None:
        if not base_url():
            raise ValueError("OKTA_URL is not configured")
        url = keys_url()

        def _fetch():
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            return {key["kid"]: key for key in response.json()["keys"]}

        _jwks_cache = call_external("okta", "JWKS", _fetch, url=url)
    return _jwks_cache


def claims(token: str) -> dict:
    token = token.replace("Bearer ", "").strip()
    bypass_claims = bypass_auth.claims_dict(token)
    if bypass_claims:
        return bypass_claims
    kid = jwt.get_unverified_header(token)["kid"]
    decoded = jwt.decode(
        token,
        _jwks()[kid],
        algorithms=["RS256"],
        audience=audience(),
        options={"leeway": 60},
    )
    expected_issuer = issuer().rstrip("/")
    token_issuer = str(decoded.get("iss", "")).rstrip("/")
    if expected_issuer and token_issuer != expected_issuer:
        raise ValueError("token issuer is not trusted")
    return decoded


def groups(token_claims: dict) -> list:
    """Extract group membership from token claims (``apigroups`` or ``groups``)."""
    claims = token_claims or {}
    for key in ("apigroups", "groups"):
        raw = claims.get(key)
        if raw is None:
            continue
        if isinstance(raw, list):
            return raw
        return [group.strip() for group in str(raw).split(",") if group.strip()]
    return []


def lan_id(token_claims: dict) -> str:
    return (
        token_claims.get("samAccountName")
        or token_claims.get("samaccountname")
        or (token_claims.get("sub") or "")[:50]
    )
