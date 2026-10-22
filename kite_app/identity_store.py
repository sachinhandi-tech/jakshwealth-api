"""Append-only login audit and the current encrypted Kite session."""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from kite_app.identity_models import IdentityUser, KiteSessionRow, LoginEvent
from kite_app.persistence import identity_session
from kite_app.session_manager import encrypt_access_token, today_ist

logger = logging.getLogger("kite_app.identity")


def active_user(platform_user_id: uuid.UUID) -> Optional[IdentityUser]:
    db = identity_session()
    try:
        user = db.get(IdentityUser, platform_user_id)
        if user is None or not user.is_active:
            return None
        return user
    finally:
        db.close()


def record_login(
    *,
    source: str,
    outcome: str,
    platform_user_id: uuid.Optional[UUID],
    api_key: str,
    session: Optional[dict],
) -> uuid.UUID:
    """Insert one login_events row. A completed exchange also replaces the session ciphertext."""
    event_id = uuid.uuid4()
    attributes = session or {}
    access_token = str(attributes.get("access_token") or "")
    public_token = attributes.get("public_token")
    refresh_token = attributes.get("refresh_token")
    last4, digest = _api_key_mark(api_key if outcome == "completed" else "")
    now = datetime.now(timezone.utc)
    from kite_app.request_context import request_id_var

    db = identity_session()
    try:
        db.add(LoginEvent(
            event_id=event_id,
            platform_user_id=platform_user_id,
            received_at=now,
            source=source,
            outcome=outcome,
            zerodha_user_id=_text(attributes.get("user_id")) if outcome == "completed" else None,
            user_name=_text(attributes.get("user_name")) if outcome == "completed" else None,
            user_shortname=_text(attributes.get("user_shortname")) if outcome == "completed" else None,
            email=_text(attributes.get("email")) if outcome == "completed" else None,
            user_type=_text(attributes.get("user_type")) if outcome == "completed" else None,
            broker=_text(attributes.get("broker")) if outcome == "completed" else None,
            exchanges=attributes.get("exchanges") if outcome == "completed" else None,
            products=attributes.get("products") if outcome == "completed" else None,
            order_types=attributes.get("order_types") if outcome == "completed" else None,
            login_time=_text(attributes.get("login_time")) if outcome == "completed" else None,
            meta=attributes.get("meta") if outcome == "completed" and isinstance(attributes.get("meta"), dict) else None,
            avatar_url=_text(attributes.get("avatar_url")) if outcome == "completed" else None,
            api_key_last4=last4,
            api_key_sha256=digest,
            request_id=request_id_var.get(),
        ))
        if outcome == "completed" and platform_user_id is not None and access_token:
            _replace_session(
                db,
                platform_user_id,
                str(attributes.get("user_id") or ""),
                access_token,
                None if not public_token else str(public_token),
                None if not refresh_token else str(refresh_token),
                now,
            )
        db.commit()
    finally:
        db.close()
    logger.info("login event_id=%s source=%s outcome=%s", event_id, source, outcome)
    return event_id


def has_active_user() -> bool:
    db = identity_session()
    try:
        found = db.scalar(select(IdentityUser.platform_user_id).where(IdentityUser.is_active.is_(True)).limit(1))
        return found is not None
    finally:
        db.close()


def open_first_user(email: str) -> uuid.Optional[UUID]:
    """Insert the first platform user. Returns None when an account already exists."""
    text_email = email.strip()
    if not text_email:
        return None
    from kite_app.persistence import admin_identity_session
    from sqlalchemy.exc import IntegrityError

    db = admin_identity_session()
    try:
        if db.scalar(select(IdentityUser.platform_user_id).limit(1)) is not None:
            return None
        user_id = uuid.uuid4()
        db.add(IdentityUser(platform_user_id=user_id, email=text_email, is_active=True))
        db.commit()
        return user_id
    except IntegrityError:
        db.rollback()
        return None
    finally:
        db.close()


def list_active_users() -> list[dict]:
    db = identity_session()
    try:
        rows = db.scalars(select(IdentityUser).where(IdentityUser.is_active.is_(True))).all()
        return [{"platform_user_id": str(row.platform_user_id), "email": row.email} for row in rows]
    finally:
        db.close()


def current_desk_session(platform_user_id: uuid.Optional[UUID] = None) -> Optional[dict]:
    """Session for this platform user whose token_date is today in Asia/Kolkata."""
    if platform_user_id is None:
        return None
    db = identity_session()
    try:
        row = db.scalar(
            select(KiteSessionRow).where(
                KiteSessionRow.platform_user_id == platform_user_id,
                KiteSessionRow.token_date == today_ist(),
            )
        )
        if row is None:
            return None
        from kite_app.session_manager import _decrypt

        event = db.scalar(
            select(LoginEvent)
            .where(
                LoginEvent.platform_user_id == row.platform_user_id,
                LoginEvent.outcome == "completed",
            )
            .order_by(LoginEvent.received_at.desc())
        )
        return {
            "platform_user_id": row.platform_user_id,
            "user_id": row.zerodha_user_id,
            "user_name": None if event is None else event.user_name,
            "access_token": _decrypt(row.encrypted_access_token),
            "saved_at": row.updated_at.isoformat(),
        }
    finally:
        db.close()


def invalidate_current_sessions(platform_user_id: uuid.Optional[UUID] = None) -> None:
    """UPDATE the current row so token_date is before today. Login events stay."""
    if platform_user_id is None:
        return
    db = identity_session()
    try:
        row = db.get(KiteSessionRow, platform_user_id)
        if row is None or row.token_date != today_ist():
            return
        row.token_date = today_ist() - timedelta(days=1)
        row.updated_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


def purge_expired_session_rows() -> int:
    """Delete current session rows from previous IST dates. login_events is not touched."""
    from sqlalchemy import delete

    db = identity_session()
    try:
        result = db.execute(delete(KiteSessionRow).where(KiteSessionRow.token_date < today_ist()))
        db.commit()
        return int(result.rowcount or 0)
    finally:
        db.close()


def _replace_session(db, platform_user_id, zerodha_user_id, access_token, public_token, refresh_token, now) -> None:
    row = db.get(KiteSessionRow, platform_user_id)
    encrypted_access = encrypt_access_token(access_token)
    encrypted_public = None if public_token is None else encrypt_access_token(public_token)
    encrypted_refresh = None if refresh_token is None else encrypt_access_token(refresh_token)
    if row is None:
        db.add(KiteSessionRow(
            platform_user_id=platform_user_id,
            zerodha_user_id=zerodha_user_id,
            encrypted_access_token=encrypted_access,
            encrypted_public_token=encrypted_public,
            encrypted_refresh_token=encrypted_refresh,
            token_date=today_ist(),
            updated_at=now,
        ))
        return
    row.zerodha_user_id = zerodha_user_id
    row.encrypted_access_token = encrypted_access
    row.encrypted_public_token = encrypted_public
    row.encrypted_refresh_token = encrypted_refresh
    row.token_date = today_ist()
    row.updated_at = now


def _api_key_mark(api_key: str) -> tuple[Optional[str], Optional[str]]:
    if not api_key:
        return None, None
    return api_key[-4:], hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _text(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
