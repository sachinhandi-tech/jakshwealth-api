"""Kite Connect calls. Access tokens stay encrypted in jakshwealth_identity."""

from __future__ import annotations

import logging
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException, TokenException

from kite_app.session_store import SessionStore

logger = logging.getLogger("kite_app.kite")
from kite_app.signals import SignalScanError, scan_nifty100

PROFILE_CACHE_SECONDS = 30
_IST = ZoneInfo("Asia/Kolkata")
QUOTE_SYMBOLS = (
    "NSE:RELIANCE",
    "NSE:TCS",
    "NSE:INFY",
    "NSE:HDFCBANK",
    "NSE:ICICIBANK",
)


class KiteAuthError(Exception):
    """Login or saved-session failure safe to show in the UI."""


def extract_request_token(raw: str) -> str:
    """Accept a raw request token or the full redirect URL Zerodha sends back."""
    text = (raw or "").strip()
    if "request_token=" not in text:
        return text
    query = urlparse(text).query if "://" in text else text.split("?", 1)[-1]
    token = parse_qs(query).get("request_token", [""])[0].strip()
    return token or text


class KiteService:
    def __init__(self, store: SessionStore | None = None) -> None:
        self.store = store or SessionStore()
        self._client: KiteConnect | None = None
        self._client_key: tuple[str, str] | None = None
        self._profile_cache: tuple[float, dict] | None = None

    def session_status(self) -> dict:
        record = self.saved_session()
        if record is None:
            return {"authenticated": False, "user_name": None, "user_id": None}
        return {
            "authenticated": True,
            "user_name": record.get("user_name") or None,
            "user_id": record.get("user_id") or None,
            "platform_user_id": None if record.get("platform_user_id") is None else str(record.get("platform_user_id")),
        }

    def login(self, request_token: str, platform_user_id: uuid.UUID | None) -> dict:
        from kite_app.identity_store import active_user, record_login
        from kite_app.models import load_platform_config

        load_platform_config()
        api_key = os.environ.get("KITE_API_KEY", "").strip()
        api_secret = os.environ.get("KITE_API_SECRET", "").strip()
        request_token = extract_request_token(request_token)
        if platform_user_id is None or active_user(platform_user_id) is None:
            if api_key:
                record_login(
                    source="kite_login",
                    outcome="subscriber_inactive",
                    platform_user_id=platform_user_id,
                    api_key=api_key,
                    session=None,
                )
            raise KiteAuthError("Subscriber is not active")
        if not request_token:
            record_login(
                source="kite_login",
                outcome="not_completed",
                platform_user_id=platform_user_id,
                api_key=api_key,
                session=None,
            )
            raise KiteAuthError("A request token is required.")
        if not api_key or not api_secret:
            raise KiteAuthError("Platform Kite app is not configured")

        kite = KiteConnect(api_key=api_key)
        try:
            session = kite.generate_session(request_token, api_secret=api_secret)
            access_token = session["access_token"]
            kite.set_access_token(access_token)
            profile = kite.profile()
        except KiteException as exc:
            record_login(
                source="kite_login",
                outcome="exchange_failed",
                platform_user_id=platform_user_id,
                api_key=api_key,
                session=None,
            )
            raise KiteAuthError(_safe_kite_message(exc)) from exc
        except KeyError as exc:
            record_login(
                source="kite_login",
                outcome="exchange_failed",
                platform_user_id=platform_user_id,
                api_key=api_key,
                session=None,
            )
            raise KiteAuthError("Zerodha did not return an access token.") from exc

        public = _public_profile(profile)
        for name in ("user_name", "user_shortname", "email", "user_type", "broker", "exchanges", "products", "order_types", "avatar_url"):
            if name in profile and name not in session:
                session[name] = profile[name]
        record_login(
            source="kite_login",
            outcome="completed",
            platform_user_id=platform_user_id,
            api_key=api_key,
            session=session,
        )
        self.store.clear()
        self._client = kite
        self._client_key = (api_key, str(session["access_token"]))
        del access_token
        del session
        self._profile_cache = (time.monotonic(), public)
        return {
            "authenticated": True,
            "user_name": public["user_name"],
            "user_id": public["user_id"],
            "platform_user_id": None if platform_user_id is None else str(platform_user_id),
        }

    def logout(self) -> dict:
        from kite_app.identity_store import invalidate_current_sessions
        from kite_app.request_context import platform_user_var

        user_id = _platform_user_id(platform_user_var.get())
        invalidate_current_sessions(user_id)
        self.store.clear()
        self._client = None
        self._client_key = None
        self._profile_cache = None
        return {"authenticated": False, "user_name": None, "user_id": None}

    def profile(self) -> dict:
        cached = self._profile_cache
        if cached and time.monotonic() - cached[0] < PROFILE_CACHE_SECONDS:
            return cached[1]
        kite = self._require_client()
        try:
            public = _public_profile(kite.profile())
        except KiteException as exc:
            self._drop_expired_session(exc)
            raise KiteAuthError(_safe_kite_message(exc)) from exc
        self._profile_cache = (time.monotonic(), public)
        return public

    def quotes(self) -> list[dict]:
        kite = self._require_client()
        try:
            raw = kite.quote(list(QUOTE_SYMBOLS))
        except KiteException as exc:
            self._drop_expired_session(exc)
            raise KiteAuthError(_safe_kite_message(exc)) from exc
        rows = []
        for symbol in QUOTE_SYMBOLS:
            item = raw.get(symbol) or {}
            last_price = _as_float(item.get("last_price"))
            previous_close = _as_float((item.get("ohlc") or {}).get("close"))
            change_percent = None
            if last_price is not None and previous_close not in (None, 0):
                change_percent = round((last_price - previous_close) / previous_close * 100, 2)
            exchange, tradingsymbol = symbol.split(":", 1)
            rows.append(
                {
                    "symbol": tradingsymbol,
                    "exchange": exchange,
                    "last_price": last_price,
                    "change_percent": change_percent,
                    "volume": _as_int(item.get("volume")),
                }
            )
        return rows

    def scan_signals(
        self,
        short_window: int,
        long_window: int,
        lookback_days: int,
        max_stocks: int,
        ma_type: str = "sma",
        short_type: str | None = None,
        long_type: str | None = None,
        trend_window: int = 0,
        scan_mode: str = "crossover",
    ) -> dict:
        kite = self._require_client()
        try:
            return scan_nifty100(kite, **self.scan_params(
                short_window, long_window, lookback_days, max_stocks,
                ma_type, short_type, long_type, trend_window, scan_mode,
            ))
        except KiteException as exc:
            if isinstance(exc, TokenException):
                self._drop_expired_session(exc)
            raise KiteAuthError(_safe_kite_message(exc)) from exc

    def scan_params(
        self,
        short_window: int,
        long_window: int,
        lookback_days: int,
        max_stocks: int,
        ma_type: str = "sma",
        short_type: str | None = None,
        long_type: str | None = None,
        trend_window: int = 0,
        scan_mode: str = "crossover",
    ) -> dict:
        fast_type = short_type or ma_type
        slow_type = long_type or ma_type
        if fast_type not in {"sma", "ema", "wma"} or slow_type not in {"sma", "ema", "wma"}:
            raise SignalScanError("Average must be SMA, EMA, or WMA.")
        if scan_mode not in {"crossover", "price"}:
            raise SignalScanError("Choose a short-term crossover or a long-term SMA.")
        if scan_mode == "price":
            if not 2 <= long_window <= 400:
                raise SignalScanError("The long-term SMA period must be between 2 and 400.")
        elif short_window < 2 or long_window <= short_window:
            raise SignalScanError("The slow period must be greater than the fast period.")
        if trend_window and not 2 <= trend_window <= 400:
            raise SignalScanError("The long-term SMA period must be between 2 and 400.")
        if not 1 <= lookback_days <= 400:
            raise SignalScanError("Lookback days must be between 1 and 400.")
        if not 1 <= max_stocks <= 100:
            raise SignalScanError("Max stocks must be between 1 and 100.")
        return {
            "short_window": short_window,
            "long_window": long_window,
            "lookback_days": lookback_days,
            "max_stocks": max_stocks,
            "ma_type": ma_type,
            "short_type": fast_type,
            "long_type": slow_type,
            "trend_window": trend_window,
            "scan_mode": scan_mode,
        }

    def saved_session(self) -> dict | None:
        from kite_app.identity_store import current_desk_session
        from kite_app.request_context import platform_user_var

        record = current_desk_session(_platform_user_id(platform_user_var.get()))
        if record is None:
            return None
        record["api_key"] = os.environ.get("KITE_API_KEY", "").strip()
        return record

    def require_session(self) -> dict:
        record = self.saved_session()
        if record is None:
            raise KiteAuthError("Log in with a fresh request token. No saved session was found.")
        return record

    def _require_client(self) -> KiteConnect:
        record = self.require_session()
        key = (str(record["api_key"]), str(record["access_token"]))
        if self._client is None or self._client_key != key:
            client = KiteConnect(api_key=key[0])
            client.set_access_token(key[1])
            self._client = client
            self._client_key = key
        self._reconcile(self._client, record)
        return self._client

    def _reconcile(self, client: KiteConnect, record: dict) -> None:
        from kite_app.session_manager import today_ist
        from kite_app.trading_store import reconcile_book

        try:
            reconcile_book(client, record.get("platform_user_id"), record.get("user_id"), today_ist().isoformat())
        except Exception as exc:
            logger.info("reconcile failed %s", type(exc).__name__)

    def _drop_expired_session(self, exc: KiteException) -> None:
        message = _safe_kite_message(exc).lower()
        if "token" in message or getattr(exc, "code", None) in (403,):
            self.logout()


def _platform_user_id(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def access_token_expired(saved_at, now: datetime | None = None) -> bool:
    """Zerodha access tokens stop working at the next 6:00 AM IST. There is no refresh token."""
    text = str(saved_at or "").strip()
    if not text:
        return False
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    saved = stamp.astimezone(_IST)
    expires = saved.replace(hour=6, minute=0, second=0, microsecond=0)
    if saved >= expires:
        expires += timedelta(days=1)
    current = now.astimezone(_IST) if now is not None else datetime.now(_IST)
    if current.tzinfo is None:
        current = current.replace(tzinfo=_IST)
    return current >= expires


def _public_profile(profile: dict) -> dict:
    products = profile.get("products") or []
    exchanges = profile.get("exchanges") or []
    return {
        "user_name": str(profile.get("user_name") or profile.get("user_shortname") or "Trader"),
        "user_id": str(profile.get("user_id") or ""),
        "products": [str(item) for item in products],
        "exchanges": [str(item) for item in exchanges],
    }


def _safe_kite_message(exc: KiteException) -> str:
    message = str(getattr(exc, "message", None) or exc)
    lowered = message.lower()
    if "access_token" in lowered or "api_secret" in lowered:
        return "Zerodha rejected the login. Check the API key, secret, and request token."
    return message or "Zerodha rejected the request."


def _as_int(value) -> int | None:
    number = _as_float(value)
    if number is None:
        return None
    return int(number)


def _as_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
