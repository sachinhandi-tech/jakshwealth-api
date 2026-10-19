"""Zerodha OAuth for subscribers. Platform credentials stay on the server."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse
from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException

from kite_app.models import User, get_sessionmaker, load_platform_config
from kite_app.session_manager import upsert_zerodha_session
from kite_app.session_store import SessionStore

logger = logging.getLogger("kite_app.auth")
router = APIRouter(tags=["zerodha-auth"])
_STATE_TTL_SECONDS = 600


@router.get("/auth/zerodha/login")
def zerodha_login(platform_user_id: uuid.UUID | None = Query(default=None)) -> RedirectResponse:
    """Send the browser to Zerodha. The API key stays in Secrets Manager."""
    if platform_user_id is not None:
        db = get_sessionmaker()()
        try:
            user = db.get(User, platform_user_id)
        finally:
            db.close()
        if user is None or not user.is_active:
            raise HTTPException(status_code=403, detail="Subscriber is not active")
        signed = _sign_state(platform_user_id)
    else:
        signed = _sign_desk_state()
    kite = KiteConnect(api_key=_api_key())
    state = quote(signed, safe="")
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
    load_platform_config()
    api_secret = os.environ.get("KITE_API_SECRET", "").strip()
    if not api_secret:
        raise HTTPException(status_code=503, detail="Platform Kite app is not configured")
    api_key = _api_key()
    kite = KiteConnect(api_key=api_key)
    try:
        session = kite.generate_session(request_token, api_secret=api_secret)
        access_token = str(session.pop("access_token"))
        zerodha_user_id = str(session.pop("user_id"))
        user_name = str(session.get("user_name") or zerodha_user_id)
    except (KiteException, KeyError, TypeError):
        logger.info("Zerodha token exchange failed")
        raise HTTPException(status_code=401, detail="Zerodha login could not be completed") from None
    SessionStore().save(
        {
            "api_key": api_key,
            "access_token": access_token,
            "user_id": zerodha_user_id,
            "user_name": user_name,
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    if platform_user_id is not None:
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


def _read_state(state: str) -> uuid.UUID | None:
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
