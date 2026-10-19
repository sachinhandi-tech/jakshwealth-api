"""Cached daily candles for the desk breakout scanner. The browser runs the scan."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from kiteconnect.exceptions import KiteException, TokenException

from kite_app.session_store import DEFAULT_SESSION_PATH
from kite_app.signals import (
    REQUEST_GAP_SECONDS,
    SignalScanError,
    load_nifty100,
    nse_equity_tokens,
    parse_nifty100_csv,
)

NIFTY50_CSV_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv"
NIFTY50_CSV_FALLBACK = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
CACHE_SECONDS = 6 * 60 * 60
HISTORY_DAYS = 120
FILL_BUDGET_SECONDS = 18


def cache_path() -> Path:
    override = os.environ.get("SCANNER_CACHE_PATH", "").strip()
    if override:
        return Path(override)
    return DEFAULT_SESSION_PATH.parent / "scanner-data.json"


def build_scanner_payload(kite, budget_seconds: float = FILL_BUDGET_SECONDS) -> dict:
    """Return the saved candle cache, filling any missing symbols until the time budget."""
    constituents = load_nifty100()
    cached = _read_cache()
    within_ttl = cached is not None and _within_ttl(cached)
    saved = {}
    if cached is not None:
        for stock in cached.get("stocks") or []:
            symbol = str(stock.get("symbol") or "")
            if symbol:
                saved[symbol] = stock
    if within_ttl and all(row["ticker"] in saved for row in constituents):
        return _public_payload(constituents, saved)

    tokens = nse_equity_tokens(kite)
    nifty50 = load_nifty50_symbols()
    deadline = time.monotonic() + budget_seconds
    end = datetime.now()
    start = end - timedelta(days=HISTORY_DAYS)
    for offset, constituent in enumerate(constituents):
        symbol = constituent["ticker"]
        if within_ttl and symbol in saved:
            continue
        if time.monotonic() >= deadline:
            break
        if offset:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(REQUEST_GAP_SECONDS, remaining))
        token = tokens.get(symbol)
        if token is None:
            continue
        try:
            raw_candles = kite.historical_data(token, start, end, "day")
        except TokenException:
            raise
        except KiteException:
            continue
        candles = [_candle_row(item) for item in raw_candles]
        candles = [item for item in candles if item is not None]
        saved[symbol] = {
            "symbol": symbol,
            "company_name": constituent["company"],
            "instrument_token": int(token),
            "nifty_flags": {"nifty50": symbol in nifty50, "nifty100": True},
            "candles": candles,
        }
    payload = _public_payload(constituents, saved)
    _write_cache(payload)
    return payload


def ohlc_snapshot(kite, symbols: list[str]) -> dict:
    names = []
    seen = set()
    for symbol in symbols:
        name = symbol.strip().upper()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    if not names:
        return {"quotes": []}
    if len(names) > 200:
        raise SignalScanError("Ask for the OHLC snapshot of at most 200 symbols.")
    try:
        raw = kite.ohlc([f"NSE:{name}" for name in names])
    except TokenException:
        raise
    except KiteException as exc:
        raise SignalScanError("Kite could not load the OHLC snapshot.") from exc
    quotes = []
    for name in names:
        item = raw.get(f"NSE:{name}") or {}
        price = item.get("last_price")
        try:
            last_price = None if price is None else float(price)
        except (TypeError, ValueError):
            last_price = None
        quotes.append({"symbol": name, "last_price": last_price})
    return {"quotes": quotes}


def load_nifty50_symbols() -> set[str]:
    for url in (NIFTY50_CSV_URL, NIFTY50_CSV_FALLBACK):
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*"},
                timeout=8,
            )
            response.raise_for_status()
            return {row["ticker"] for row in parse_nifty100_csv(response.text)}
        except (SignalScanError, requests.RequestException, OSError):
            continue
    return set()


def _public_payload(constituents: list[dict], saved: dict[str, dict]) -> dict:
    stocks = [saved[row["ticker"]] for row in constituents if row["ticker"] in saved]
    return {
        "metadata": {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "universe": len(constituents),
            "cached_stocks": len(stocks),
            "complete": len(stocks) == len(constituents) and len(constituents) > 0,
            "interval": "day",
        },
        "stocks": stocks,
    }


def _within_ttl(payload: dict) -> bool:
    saved_at = str((payload.get("metadata") or {}).get("as_of") or "")
    try:
        stamp = datetime.fromisoformat(saved_at)
    except ValueError:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - stamp
    return age.total_seconds() <= CACHE_SECONDS


def _read_cache() -> dict | None:
    path = cache_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("stocks"), list):
        return None
    return payload


def _write_cache(payload: dict) -> None:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _candle_row(raw: dict) -> dict | None:
    try:
        value = raw.get("date")
        if isinstance(value, datetime):
            date_text = value.date().isoformat()
        else:
            date_text = str(value)[:10]
        if len(date_text) != 10:
            return None
        return {
            "date": date_text,
            "open": float(raw["open"]),
            "high": float(raw["high"]),
            "low": float(raw["low"]),
            "close": float(raw["close"]),
            "volume": float(raw["volume"]),
        }
    except (TypeError, ValueError, KeyError):
        return None
