"""Cached daily candles for the desk breakout scanner.

The universe is every NSE equity from Kite. The HTTP body returns only the
breakout setups; the full candle cache stays on disk or in S3.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from kiteconnect.exceptions import KiteException, TokenException

from kite_app.breakout_scan import triggered_rows
from kite_app.session_store import DEFAULT_SESSION_PATH
from kite_app.signals import (
    REQUEST_GAP_SECONDS,
    SignalScanError,
    load_nifty100,
    parse_nifty100_csv,
)

NIFTY50_CSV_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv"
NIFTY50_CSV_FALLBACK = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
CACHE_SECONDS = 6 * 60 * 60
HISTORY_DAYS = 120
FILL_BUDGET_SECONDS = 18
_universe_cache: tuple[float, list[dict]] | None = None


def cache_path() -> Path:
    override = os.environ.get("SCANNER_CACHE_PATH", "").strip()
    if override:
        return Path(override)
    return DEFAULT_SESSION_PATH.parent / "scanner-data.json"


def equity_universe(kite) -> list[dict]:
    """Every NSE equity Zerodha lists. This is the Algo Signals universe."""
    global _universe_cache
    now = time.monotonic()
    if _universe_cache and now - _universe_cache[0] < CACHE_SECONDS:
        return _universe_cache[1]
    try:
        instruments = kite.instruments("NSE") or []
    except TokenException:
        raise
    except KiteException as exc:
        raise SignalScanError("Kite could not load NSE instruments.") from exc
    rows = []
    seen = set()
    for instrument in instruments:
        if not isinstance(instrument, dict):
            continue
        if instrument.get("exchange") != "NSE" or instrument.get("instrument_type") != "EQ":
            continue
        segment = str(instrument.get("segment") or "NSE")
        if segment != "NSE":
            continue
        symbol = str(instrument.get("tradingsymbol") or "").strip().upper()
        token = instrument.get("instrument_token")
        if not symbol or symbol in seen or token is None:
            continue
        seen.add(symbol)
        company = str(instrument.get("name") or symbol).strip() or symbol
        rows.append({"ticker": symbol, "company": company, "token": int(token)})
    rows.sort(key=lambda row: row["ticker"])
    if not rows:
        raise SignalScanError("Kite returned no NSE equity instruments.")
    _universe_cache = (now, rows)
    return rows


def build_scanner_payload(kite, budget_seconds: float | None = None) -> dict:
    """Return the saved candle cache, filling any missing NSE symbols until the time budget."""
    if budget_seconds is None:
        budget_seconds = float(os.environ.get("SCANNER_FILL_BUDGET_SECONDS", str(FILL_BUDGET_SECONDS)))
    constituents = equity_universe(kite)
    cached = _read_cache()
    within_ttl = cached is not None and _within_ttl(cached)
    saved = {}
    if cached is not None:
        for stock in cached.get("stocks") or []:
            symbol = str(stock.get("symbol") or "")
            if symbol:
                saved[symbol] = stock
    recorded_all = bool(constituents) and all(row["ticker"] in saved for row in constituents)
    if recorded_all and within_ttl:
        return _public_payload(constituents, saved)
    if recorded_all and not within_ttl:
        saved = {}

    nifty100 = _nifty_tickers(load_nifty100)
    nifty50 = load_nifty50_symbols()
    deadline = time.monotonic() + budget_seconds
    end = datetime.now()
    start = end - timedelta(days=HISTORY_DAYS)
    for offset, constituent in enumerate(constituents):
        symbol = constituent["ticker"]
        if symbol in saved:
            continue
        if time.monotonic() >= deadline:
            break
        if offset:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(REQUEST_GAP_SECONDS, remaining))
        token = constituent.get("token")
        if token is None:
            saved[symbol] = _empty_stock(constituent, nifty50, nifty100)
            continue
        try:
            raw_candles = kite.historical_data(token, start, end, "day")
        except TokenException:
            raise
        except KiteException:
            saved[symbol] = _empty_stock(constituent, nifty50, nifty100)
            continue
        candles = [_candle_row(item) for item in raw_candles]
        candles = [item for item in candles if item is not None]
        saved[symbol] = {
            "symbol": symbol,
            "company_name": constituent["company"],
            "instrument_token": int(token),
            "nifty_flags": {"nifty50": symbol in nifty50, "nifty100": symbol in nifty100},
            "candles": candles,
        }
    _write_cache(_cache_payload(constituents, saved))
    return _public_payload(constituents, saved)


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


def _nifty_tickers(loader) -> set[str]:
    try:
        rows = loader()
    except Exception:
        return set()
    return {str(row.get("ticker") or "").upper() for row in rows if isinstance(row, dict) and row.get("ticker")}


def _empty_stock(constituent: dict, nifty50: set[str], nifty100: set[str]) -> dict:
    symbol = constituent["ticker"]
    return {
        "symbol": symbol,
        "company_name": constituent["company"],
        "instrument_token": constituent.get("token"),
        "nifty_flags": {"nifty50": symbol in nifty50, "nifty100": symbol in nifty100},
        "candles": [],
    }


def _cache_payload(constituents: list[dict], saved: dict[str, dict]) -> dict:
    return {
        "metadata": {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "universe": len(constituents),
        },
        "stocks": [saved[row["ticker"]] for row in constituents if row["ticker"] in saved],
    }


def _public_payload(constituents: list[dict], saved: dict[str, dict]) -> dict:
    recorded = [saved[row["ticker"]] for row in constituents if row["ticker"] in saved]
    with_candles = [stock for stock in recorded if stock.get("candles")]
    return {
        "metadata": {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "universe": len(constituents),
            "cached_stocks": len(with_candles),
            "scanned": len(recorded),
            "complete": len(recorded) == len(constituents) and len(constituents) > 0,
            "interval": "day",
        },
        "stocks": triggered_rows(with_candles),
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
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("stocks"), list):
            return payload
    return _read_s3_cache()


def _write_cache(payload: dict) -> None:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    _write_s3_cache(payload)


def _cache_bucket() -> str:
    return os.environ.get("SCANNER_CACHE_BUCKET", "").strip()


def _cache_key() -> str:
    return os.environ.get("SCANNER_CACHE_KEY", "kite-scanner/scanner-data.json").strip() or "kite-scanner/scanner-data.json"


def _read_s3_cache() -> dict | None:
    bucket = _cache_bucket()
    if not bucket:
        return None
    try:
        import boto3

        body = boto3.client("s3").get_object(Bucket=bucket, Key=_cache_key())["Body"].read()
        payload = json.loads(body)
    except Exception:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("stocks"), list):
        return None
    return payload


def _write_s3_cache(payload: dict) -> None:
    bucket = _cache_bucket()
    if not bucket:
        return
    try:
        import boto3

        boto3.client("s3").put_object(
            Bucket=bucket,
            Key=_cache_key(),
            Body=json.dumps(payload).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception:
        return


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
