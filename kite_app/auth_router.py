"""Zerodha OAuth for subscribers. Platform credentials stay on the server."""

import hashlib
import hmac
import logging
import os
import time
import uuid
from typing import Optional
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException

from kite_app.identity_store import active_user, has_active_user, open_first_user, record_login
from kite_app.models import load_platform_config
from kite_app.session_store import SessionStore

logger = logging.getLogger("kite_app.auth")
router = APIRouter(tags=["zerodha-auth"])
_STATE_TTL_SECONDS = 600


@router.get("/auth/zerodha/login")
def zerodha_login(platform_user_id: str = Query(None)) -> RedirectResponse:
    """Send the browser to Zerodha. The first sign-in opens the account."""
    platform_uuid = None
    if platform_user_id:
        try:
            platform_uuid = uuid.UUID(platform_user_id)
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="Invalid platform_user_id")

    if platform_uuid is None:
        if has_active_user():
            raise HTTPException(status_code=403, detail="Subscriber is not active")
        signed = _sign_desk_state()
    elif active_user(platform_uuid) is None:
        raise HTTPException(status_code=403, detail="Subscriber is not active")
    else:
        signed = _sign_state(platform_uuid)
    kite = KiteConnect(api_key=_api_key())
    state = quote(signed, safe="")
    return RedirectResponse(url=f"{kite.login_url()}&redirect_params=state%3D{state}", status_code=302)


@router.get("/auth/zerodha/callback")
def zerodha_callback(
    request_token: str = Query(default=""),
    state: str = Query(default=""),
    status: str = Query(default=""),
) -> RedirectResponse:
    """Exchange the one-time request token and store only the encrypted access token.

    The postback URL is not this route. The Kite developer console still has to
    be given the postback URL. That console step is outside this code.
    """
    platform_user_id = None
    state_error = None
    if state:
        try:
            platform_user_id = _read_state(state)
        except HTTPException as exc:
            state_error = exc
    if state_error is not None:
        raise state_error
    api_key = _api_key()
    if status == "error" or not request_token:
        record_login(
            source="auth_callback",
            outcome="not_completed",
            platform_user_id=platform_user_id,
            api_key=api_key,
            session=None,
        )
        raise HTTPException(status_code=400, detail="Zerodha login was not completed")
    opening_account = platform_user_id is None and not has_active_user()
    if not opening_account and (platform_user_id is None or active_user(platform_user_id) is None):
        record_login(
            source="auth_callback",
            outcome="subscriber_inactive",
            platform_user_id=platform_user_id,
            api_key=api_key,
            session=None,
        )
        raise HTTPException(status_code=403, detail="Subscriber is not active")
    load_platform_config()
    api_secret = os.environ.get("KITE_API_SECRET", "").strip()
    if not api_secret:
        raise HTTPException(status_code=503, detail="Platform Kite app is not configured")
    kite = KiteConnect(api_key=api_key)
    try:
        session = kite.generate_session(request_token, api_secret=api_secret)
        access_token = str(session["access_token"])
    except (KiteException, KeyError, TypeError):
        record_login(
            source="auth_callback",
            outcome="exchange_failed",
            platform_user_id=platform_user_id,
            api_key=api_key,
            session=None,
        )
        logger.info("Zerodha token exchange failed")
        raise HTTPException(status_code=401, detail="Zerodha login could not be completed") from None
    if opening_account:
        email = str(session.get("email") or session.get("user_id") or "").strip()
        platform_user_id = open_first_user(email)
        if platform_user_id is None:
            record_login(
                source="auth_callback",
                outcome="subscriber_inactive",
                platform_user_id=None,
                api_key=api_key,
                session=None,
            )
            raise HTTPException(status_code=403, detail="Subscriber is not active")
    record_login(
        source="auth_callback",
        outcome="completed",
        platform_user_id=platform_user_id,
        api_key=api_key,
        session=session,
    )
    SessionStore().clear()
    del access_token
    del session
    destination = _with_platform_user(
        os.environ.get(
            "KITE_POST_LOGIN_URL",
            "https://d33hvt9s5bgs3.cloudfront.net/kite/dashboard",
        ),
        platform_user_id,
    )
    return RedirectResponse(url=destination, status_code=302)


def _with_platform_user(destination: str, platform_user_id: uuid.UUID) -> str:
    parts = urlsplit(destination)
    query = dict(parse_qsl(parts.query))
    query["platform_user_id"] = str(platform_user_id)
    return urlunsplit(parts._replace(query=urlencode(query)))


def _api_key() -> str:
    load_platform_config()
    api_key = os.environ.get("KITE_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="Platform Kite app is not configured")
    return api_key


def _sign_state(platform_user_id: uuid.UUID) -> str:
    expiry = int(time.time()) + _STATE_TTL_SECONDS
    payload = f"{platform_user_id}.{expiry}"
    return f"{payload}.{_mac(payload)}"


def _sign_desk_state() -> str:
    expiry = int(time.time()) + _STATE_TTL_SECONDS
    payload = f"desk.{expiry}"
    return f"{payload}.{_mac(payload)}"


def _read_state(state: str) -> Optional[uuid.UUID]:
    parts = state.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="Zerodha login state is invalid")
    payload = f"{parts[0]}.{parts[1]}"
    if not hmac.compare_digest(_mac(payload), parts[2]):
        raise HTTPException(status_code=400, detail="Zerodha login state is invalid")
    try:
        expiry = int(parts[1])
    except ValueError:
        raise HTTPException(status_code=400, detail="Zerodha login state is invalid") from None
    if expiry < int(time.time()):
        raise HTTPException(status_code=400, detail="Zerodha login state has expired")
    if parts[0] == "desk":
        return None
    try:
        return uuid.UUID(parts[0])
    except ValueError:
        raise HTTPException(status_code=400, detail="Zerodha login state is invalid") from None


def _mac(payload: str) -> str:
    secret = os.environ.get("KITE_STATE_SECRET", "").encode("utf-8")
    if not secret:
        raise HTTPException(status_code=503, detail="Platform Kite app is not configured")
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
