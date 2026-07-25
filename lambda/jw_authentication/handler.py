"""Authentication service for JakshWealth."""

from __future__ import annotations

from urllib.parse import urlencode

import authentication_debug as debug
import bypass_auth
import config
import cors
import okta
import responses
from roles import resolve_roles
from jw_log import Request

config.load_config()
_SERVICE = "jw_authentication"


def handler(event, context):
    req = Request(_SERVICE, event, context)
    responses.bind_request_origin(event)
    try:
        method = (event or {}).get("httpMethod")
        if method == "GET":
            response = _get(event, req)
        elif method == "OPTIONS":
            response = responses.options()
        else:
            response = responses.method_not_allowed(f"{method} not supported")
        return req.complete(response)
    except Exception as exc:  # pragma: no cover - defensive catch-all
        return req.fail(exc, responses.error("An unexpected error occurred."))


def _header(event, name):
    headers = (event or {}).get("headers") or {}
    target = name.lower().replace("_", "-")
    for key, value in headers.items():
        if isinstance(key, str) and key.lower().replace("_", "-") == target and value:
            return value
    return None


def _query(event, name):
    return ((event or {}).get("queryStringParameters") or {}).get(name)


def _get(event, req: Request):
    if _wants_bypass(event):
        return _session_from_bypass(event, req)

    code = _header(event, "auth_code") or _query(event, "code") or _query(event, "auth_code")
    if code:
        return _session_from_code(event, code, req)

    refresh_token = _header(event, "refresh_token")
    if refresh_token:
        return _session_from_refresh(refresh_token, req)

    bearer = _header(event, "Authorization")
    if bearer:
        return _validate(bearer, req)

    return responses.bad_request("No authorization code or token supplied")


def _frontend_url(event):
    return cors.resolve_frontend_base(event)


def _wants_redirect(event):
    value = _query(event, "redirect") or _header(event, "redirect")
    return str(value or "").strip().lower() in ("1", "true", "yes")


def _wants_bypass(event):
    value = _query(event, "bypass") or _header(event, "bypass")
    return str(value or "").strip().lower() in ("1", "true", "yes")


def _required_groups():
    return config.required_global_groups()


def _access_fields(caller_groups: list[str]) -> dict:
    required = _required_groups()
    matched = sorted(set(caller_groups) & set(required))
    return {
        "hasAppAccess": bool(matched),
        "requiredGroups": required,
        "roles": resolve_roles(caller_groups),
    }


def _note_session(req: Request, phase: str, lan_id: str, caller_groups: list[str]) -> None:
    membership = debug.membership_summary(caller_groups)
    req.note(
        phase=phase,
        lanId=lan_id,
        hasAccess=membership["inUserGg"] or membership["inAdminGg"],
        **membership,
    )


def _build_session(tokens, req: Request, phase: str = "login"):
    access = okta.claims(tokens["access_token"], verify=False)
    identity = okta.claims(tokens["id_token"], verify=False) if tokens.get("id_token") else {}
    caller_groups = okta.groups(access)
    lan_id = okta.lan_id(access)
    _note_session(req, phase, lan_id, caller_groups)
    return {
        "firstName": identity.get("firstName") or identity.get("given_name", ""),
        "lastName": identity.get("lastName") or identity.get("family_name", ""),
        "lanId": lan_id,
        "email": access.get("email") or identity.get("email", ""),
        "department": access.get("department", ""),
        "globalGroups": caller_groups,
        "accessToken": tokens["access_token"],
        "refreshToken": tokens.get("refresh_token", ""),
        "expiresAt": access.get("exp"),
        **_access_fields(caller_groups),
    }


def _session_from_code(event, code, req: Request):
    if not okta.is_configured():
        return responses.error("Okta is not configured")
    redirect_uri = _frontend_url(event).rstrip("/") + okta.redirect_path()
    try:
        tokens = okta.exchange_authorization_code(code, redirect_uri)
    except Exception as exc:
        message = f"Okta token exchange failed: {exc}"
        if _wants_redirect(event):
            return responses.redirect(_authorize_redirect(event, error=message))
        return responses.unauthorized(message)

    session = _build_session(tokens, req, phase="authorization_code")
    if _wants_redirect(event):
        return responses.redirect(_authorize_redirect(event, session=session))
    return responses.ok(session)


def _session_from_refresh(refresh_token, req: Request):
    if not okta.is_configured():
        return responses.error("Okta is not configured")
    try:
        tokens = okta.refresh(refresh_token)
    except Exception as exc:
        return responses.unauthorized(f"Token refresh failed: {exc}")

    session = _build_session(tokens, req, phase="refresh_token")
    session["refreshToken"] = session["refreshToken"] or refresh_token
    return responses.ok(session)


def _session_from_bypass(event, req: Request):
    if not bypass_auth.bypass_okta_enabled():
        return responses.bad_request("Okta bypass is not enabled")

    lan_id = bypass_auth.bypass_lan_id()
    groups = bypass_auth.bypass_groups()
    access_token = bypass_auth.issue_access_token(lan_id, groups)
    parsed = bypass_auth.parse_access_token(access_token) or {}
    expires_at = parsed.get("exp")
    _note_session(req, "bypass_login", lan_id, groups)
    session = {
        "firstName": "Bypass",
        "lastName": "User",
        "lanId": lan_id,
        "email": f"{lan_id.lower()}@example.com",
        "department": "",
        "globalGroups": groups,
        "accessToken": access_token,
        "refreshToken": "",
        "expiresAt": expires_at,
        **_access_fields(groups),
    }
    if _wants_redirect(event):
        return responses.redirect(_authorize_redirect(event, session=session))
    return responses.ok(session)


def _validate(bearer, req: Request):
    try:
        token_claims = okta.claims(bearer, verify=True)
    except Exception as exc:
        return responses.unauthorized(f"Invalid token: {exc}")

    groups = okta.groups(token_claims)
    lan_id = okta.lan_id(token_claims)
    _note_session(req, "validate_token", lan_id, groups)
    return responses.ok({"expiresAt": token_claims.get("exp"), "groups": groups, **_access_fields(groups)})


def _authorize_redirect(event, session=None, error=None):
    base = _frontend_url(event).rstrip("/") + okta.redirect_path()
    if error:
        return f"{base}?{urlencode({'error': error})}"
    exp = session.get("expiresAt")
    params = {
        "firstName": session.get("firstName", ""),
        "lastName": session.get("lastName", ""),
        "lanId": session.get("lanId", ""),
        "email": session.get("email", ""),
        "department": session.get("department", ""),
        "accessToken": session.get("accessToken", ""),
        "refreshToken": session.get("refreshToken", ""),
        "expiresAt": str(int(exp)) if exp else "",
        "globalGroups": ",".join(session.get("globalGroups") or []),
    }
    return f"{base}#{urlencode(params)}"
