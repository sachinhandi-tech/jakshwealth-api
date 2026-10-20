"""Load a per-subscriber Kite client from the encrypted daily session."""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken
from kiteconnect import KiteConnect
from sqlalchemy.orm import Session

from kite_app.models import ZerodhaSession, load_platform_config

_IST = ZoneInfo("Asia/Kolkata")


class SessionExpiredException(Exception):
    """Raised when the subscriber has no access token for today."""


def today_ist() -> date:
    """Trading date used to expire Kite tokens after the morning reset."""
    return datetime.now(_IST).date()


def encrypt_access_token(access_token: str) -> str:
    """Return a Fernet ciphertext. The plaintext token is not retained."""
    if not access_token:
        raise SessionExpiredException("empty access token")
    return _fernet().encrypt(access_token.encode("utf-8")).decode("ascii")


def upsert_zerodha_session(
    db: Session,
    platform_user_id: uuid.UUID,
    zerodha_user_id: str,
    access_token: str,
) -> None:
    """Insert or replace today's encrypted token for one subscriber."""
    ciphertext = encrypt_access_token(access_token)
    row = db.get(ZerodhaSession, platform_user_id)
    now = datetime.now(timezone.utc)
    if row is None:
        db.add(
            ZerodhaSession(
                platform_user_id=platform_user_id,
                zerodha_user_id=zerodha_user_id,
                encrypted_access_token=ciphertext,
                token_date=today_ist(),
                updated_at=now,
            )
        )
    else:
        row.zerodha_user_id = zerodha_user_id
        row.encrypted_access_token = ciphertext
        row.token_date = today_ist()
        row.updated_at = now
    db.commit()


def get_active_kite_client(platform_user_id: str) -> KiteConnect:
    """Return a Kite client whose access token is valid for today in IST."""
    from kite_app.identity_models import KiteSessionRow
    from kite_app.identity_store import active_user
    from kite_app.persistence import identity_session

    user_id = uuid.UUID(platform_user_id)
    if active_user(user_id) is None:
        raise SessionExpiredException("subscriber is not active")
    db = identity_session()
    try:
        row = db.get(KiteSessionRow, user_id)
        if row is None or row.token_date != today_ist():
            raise SessionExpiredException("zerodha session is missing or stale")
        token = _decrypt(row.encrypted_access_token)
    finally:
        db.close()
    kite = KiteConnect(api_key=_platform_api_key())
    kite.set_access_token(token)
    return kite


def purge_expired_sessions() -> int:
    """Delete identity session rows from previous IST dates. login_events stays.

    Run after 06:00 IST. The comment on the previous table said the same.
    """
    from kite_app.identity_store import purge_expired_session_rows

    return purge_expired_session_rows()


def _decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise SessionExpiredException("stored zerodha token cannot be read") from exc


def _fernet() -> Fernet:
    return Fernet(os.environ["FERNET_KEY"].encode("ascii"))


def _platform_api_key() -> str:
    load_platform_config()
    api_key = os.environ.get("KITE_API_KEY", "").strip()
    if not api_key:
        raise SessionExpiredException("platform kite api key is not configured")
    return api_key
