"""Zerodha OAuth for subscribers. Platform credentials stay on the server."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import uuid
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException

from kite_app.models import User, get_sessionmaker
from kite_app.session_manager import upsert_zerodha_session

logger = logging.getLogger("kite_app.auth")
router = APIRouter(tags=["zerodha-auth"])
_STATE_TTL_SECONDS = 600


@router.get("/auth/zerodha/login")
def zerodha_login(platform_user_id: uuid.UUID = Query()) -> RedirectResponse:
    """Send an active subscriber to the platform Kite login. No subscriber secret is accepted."""
    db = get_sessionmaker()()
    try:
        user = db.get(User, platform_user_id)
    finally:
        db.close()
    if user is None or not user.is_active:
        raise HTTPException(status_code=403, detail="Subscriber is not active")
    kite = KiteConnect(api_key=_api_key())
    state = quote(_sign_state(platform_user_id), safe="")
    return RedirectResponse(url=f"{kite.login_url()}&redirect_params=state%3D{state}", status_code=302)


@router.get("/auth/zerodha/callback")
def zerodha_callback(
    request_token: str = Query(default=""),
    state: str = Query(default=""),
    status: str = Query(default=""),
) -> RedirectResponse:
    """Exchange the one-time request token and store only the encrypted access token."""
    if status == "error" or not request_token:
        raise HTTPException(status_code=400, detail="Zerodha login was not completed")
    platform_user_id = _read_state(state)
    api_secret = os.environ.get("KITE_API_SECRET", "").strip()
    if not api_secret:
        raise HTTPException(status_code=503, detail="Platform Kite app is not configured")
    kite = KiteConnect(api_key=_api_key())
    try:
        session = kite.generate_session(request_token, api_secret=api_secret)
        access_token = str(session.pop("access_token"))
        zerodha_user_id = str(session.pop("user_id"))
    except (KiteException, KeyError, TypeError):
        logger.info("Zerodha token exchange failed for %s", platform_user_id)
        raise HTTPException(status_code=401, detail="Zerodha login could not be completed") from None
    db = get_sessionmaker()()
    try:
        user = db.get(User, platform_user_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=403, detail="Subscriber is not active")
        upsert_zerodha_session(db, platform_user_id, zerodha_user_id, access_token)
    finally:
        db.close()
        del access_token
    destination = os.environ.get(
        "KITE_POST_LOGIN_URL",
        "https://d33hvt9s5bgs3.cloudfront.net/kite/dashboard",
    )
    return RedirectResponse(url=destination, status_code=302)


def _api_key() -> str:
    api_key = os.environ.get("KITE_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="Platform Kite app is not configured")
    return api_key


def _sign_state(platform_user_id: uuid.UUID) -> str:
    expiry = int(time.time()) + _STATE_TTL_SECONDS
    payload = f"{platform_user_id}.{expiry}"
    return f"{payload}.{_mac(payload)}"


def _read_state(state: str) -> uuid.UUID:
    parts = state.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="Zerodha login state is invalid")
    payload = f"{parts[0]}.{parts[1]}"
    if not hmac.compare_digest(_mac(payload), parts[2]):
        raise HTTPException(status_code=400, detail="Zerodha login state is invalid")
    try:
        expiry = int(parts[1])
        platform_user_id = uuid.UUID(parts[0])
    except ValueError:
        raise HTTPException(status_code=400, detail="Zerodha login state is invalid") from None
    if expiry < int(time.time()):
        raise HTTPException(status_code=400, detail="Zerodha login state has expired")
    return platform_user_id


def _mac(payload: str) -> str:
    secret = os.environ.get("KITE_STATE_SECRET", "").encode("utf-8")
    if not secret:
        raise HTTPException(status_code=503, detail="Platform Kite app is not configured")
    return hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).hexdigest()
