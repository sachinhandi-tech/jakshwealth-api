"""Okta OIDC client: authorization-code exchange, refresh, and JWT handling.

All configuration is read from the process environment (populated by
``config.load_config()``):

    OKTA_URL            Authorization-server base, e.g.
                        https://<org>.okta.com/oauth2/default/v1
    OKTA_CLIENT_ID      Confidential client id
    OKTA_CLIENT_SECRET  Confidential client secret
    OKTA_ISSUER         Expected ``iss`` claim
    OKTA_AUDIENCE       Expected ``aud`` claim (default ``api://default``)
    OKTA_REDIRECT_PATH  Front-end callback path (default ``/authorize``)
"""

from __future__ import annotations

import json
import os

import bypass_auth
import requests
from jose import jwt
from jw_log import call_external

_TIMEOUT = 30
_jwks_cache: dict | None = None


def base_url() -> str:
    return os.environ.get("OKTA_URL", "").rstrip("/")


def client_id() -> str:
    return os.environ.get("OKTA_CLIENT_ID", "")


def _client_secret() -> str:
    return os.environ.get("OKTA_CLIENT_SECRET", "")


def issuer() -> str:
    return os.environ.get("OKTA_ISSUER", "")


def audience() -> str:
    return os.environ.get("OKTA_AUDIENCE", "api://default")


def redirect_path() -> str:
    return os.environ.get("OKTA_REDIRECT_PATH", "/authorize")


def _endpoint_url(path_env_key: str, default_suffix: str) -> str:
    """Build an Okta endpoint URL from OKTA_URL and an optional path env var."""
    base = base_url()
    if not base:
        return ""
    configured = os.environ.get(path_env_key, "").strip()
    if configured:
        if configured.startswith("http"):
            return configured
        # OKTA_URL often ends with /v1 while the secret path also starts with /v1.
        if base.endswith("/v1") and configured.startswith("/v1"):
            configured = configured[3:]
        return f"{base}{configured}" if configured.startswith("/") else f"{base}/{configured}"
    return f"{base}/{default_suffix.lstrip('/')}"


def token_url() -> str:
    return _endpoint_url("OKTA_TOKEN_PATH", "token")


def keys_url() -> str:
    return _endpoint_url("OKTA_KEYS_PATH", "keys")


def is_configured() -> bool:
    return bool(base_url() and client_id())


def exchange_authorization_code(code: str, redirect_uri: str) -> dict:
    return _token_request(
        {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri}
    )


def refresh(refresh_token: str) -> dict:
    return _token_request(
        {"grant_type": "refresh_token", "refresh_token": refresh_token}
    )


def _token_request(payload: dict) -> dict:
    body = {"client_id": client_id(), "client_secret": _client_secret(), **payload}
    url = token_url()

    def _post():
        response = requests.post(url, data=body, timeout=_TIMEOUT)
        if not response.ok:
            detail = response.text.strip() or response.reason
            raise requests.HTTPError(
                f"{response.status_code} from {url} (client_id={client_id()!r}, "
                f"redirect_uri={payload.get('redirect_uri')!r}): {detail}",
                response=response,
            )
        return response.json()

    return call_external(
        "okta",
        "Token",
        _post,
        url=url,
        grantType=payload.get("grant_type"),
    )


def _jwks() -> dict:
    global _jwks_cache
    if _jwks_cache is None:
        url = keys_url()

        def _fetch():
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            return {key["kid"]: key for key in response.json()["keys"]}

        _jwks_cache = call_external("okta", "JWKS", _fetch, url=url)
    return _jwks_cache


def claims(token: str, verify: bool = True) -> dict:
    token = token.replace("Bearer ", "").strip()
    bypass_claims = bypass_auth.claims_dict(token)
    if bypass_claims:
        return bypass_claims
    if not verify:
        return jwt.get_unverified_claims(token)

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
