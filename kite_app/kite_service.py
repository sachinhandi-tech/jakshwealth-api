"""Kite Connect calls. Access tokens stay in the session file and are never returned."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException, TokenException

from kite_app.session_store import SessionStore
from kite_app.signals import SignalScanError, scan_nifty100

PROFILE_CACHE_SECONDS = 30
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
        record = self.store.load()
        if record is None:
            return {"authenticated": False, "user_name": None, "user_id": None}
        return {
            "authenticated": True,
            "user_name": record.get("user_name") or None,
            "user_id": record.get("user_id") or None,
        }

    def login(self, api_key: str, api_secret: str, request_token: str) -> dict:
        api_key = api_key.strip()
        api_secret = api_secret.strip()
        request_token = extract_request_token(request_token)
        if not api_key or not api_secret or not request_token:
            raise KiteAuthError("API key, API secret, and request token are required.")

        kite = KiteConnect(api_key=api_key)
        try:
            session = kite.generate_session(request_token, api_secret=api_secret)
            access_token = session["access_token"]
            kite.set_access_token(access_token)
            profile = kite.profile()
        except KiteException as exc:
            raise KiteAuthError(_safe_kite_message(exc)) from exc
        except KeyError as exc:
            raise KiteAuthError("Zerodha did not return an access token.") from exc

        public = _public_profile(profile)
        self.store.save(
            {
                "api_key": api_key,
                "access_token": access_token,
                "user_id": public["user_id"],
                "user_name": public["user_name"],
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._client = kite
        self._client_key = (api_key, access_token)
        self._profile_cache = (time.monotonic(), public)
        return {
            "authenticated": True,
            "user_name": public["user_name"],
            "user_id": public["user_id"],
        }

    def logout(self) -> dict:
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
        record = self.store.load()
        if record is not None:
            record["user_id"] = public["user_id"]
            record["user_name"] = public["user_name"]
            self.store.save(record)
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
        kite = self._require_client()
        try:
            return scan_nifty100(
                kite,
                short_window,
                long_window,
                lookback_days,
                max_stocks,
                ma_type,
                fast_type,
                slow_type,
                trend_window,
                scan_mode,
            )
        except KiteException as exc:
            if isinstance(exc, TokenException):
                self._drop_expired_session(exc)
            raise KiteAuthError(_safe_kite_message(exc)) from exc

    def _require_client(self) -> KiteConnect:
        record = self.store.load()
        if record is None:
            raise KiteAuthError("Log in with a fresh request token. No saved session was found.")
        key = (str(record["api_key"]), str(record["access_token"]))
        if self._client is None or self._client_key != key:
            client = KiteConnect(api_key=key[0])
            client.set_access_token(key[1])
            self._client = client
            self._client_key = key
        return self._client

    def _drop_expired_session(self, exc: KiteException) -> None:
        message = _safe_kite_message(exc).lower()
        if "token" in message or getattr(exc, "code", None) in (403,):
            self.logout()


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
