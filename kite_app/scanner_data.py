"""Cached daily candles for the desk breakout scanner.

The universe is regular NSE equity. The HTTP body returns only the breakout
setups; the full candle cache stays on disk or in S3.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

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
# Series Zerodha appends after a hyphen. These are not the normal equity series.
_OTHER_SERIES = frozenset({
    "SM", "ST", "SZ",
    "GS", "GB", "SG", "TB",
    "IV", "RR", "RE",
    "E1", "P1",
    "MF", "ME", "MT",
    "ID", "DR", "IT", "IL",
    "W1", "W2",
    "Y1", "Y2", "Y3", "Y4", "Y5", "Y6", "Y7", "Y8", "Y9",
    "Z1", "Z2", "Z3", "Z4", "Z5", "Z6", "Z7", "Z8", "Z9",
    *(f"N{digit}" for digit in range(10)),
    *(f"N{letter}" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
})
_universe_cache: Optional[tuple[float, list[dict]]] = None


def cached_equity() -> list[dict]:
    """Saved candles for every symbol already on the scanner cache."""
    cached = _read_cache()
    if not cached:
        return []
    stocks = []
    for stock in cached.get("stocks") or []:
        if isinstance(stock, dict) and stock.get("symbol") and stock.get("candles"):
            stocks.append(stock)
    return stocks


def cache_path() -> Path:
    override = os.environ.get("SCANNER_CACHE_PATH", "").strip()
    if override:
        return Path(override)
    return DEFAULT_SESSION_PATH.parent / "scanner-data.json"


_INDEX_UNDERLYINGS = frozenset({
    "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50",
    "SENSEX", "BANKEX", "NIFTYIT", "NIFTYMIDSELECT",
})
_DEBT_MARKERS = ("DEBENTURE", "PREFERENCE", "PREF SHARE", " NCD", "WARRANT", "RIGHTS ENTITLEMENT")


def _regular_equity(symbol: str, company: str) -> bool:
    """EQ-series shares. Drops SME, debt, bonds, rights, warrants, and ETFs."""
    name = company.upper()
    if "ETF" in name or "EXCHANGE TRADED" in name or "GOLD BOND" in name:
        return False
    if any(marker in name for marker in _DEBT_MARKERS):
        return False
    if symbol.isdigit():
        return False
    if "-" not in symbol:
        return True
    return symbol.rsplit("-", 1)[-1] not in _OTHER_SERIES


def _as_date(value: object) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "")[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _load_instruments(kite, exchange: str) -> list:
    try:
        return list(kite.instruments(exchange) or [])
    except TokenException:
        raise
    except KiteException as exc:
        if exchange == "NSE":
            raise SignalScanError("Kite could not load NSE instruments.") from exc
        return []


def equity_universe(kite) -> list[dict]:
    """NSE cash shares only. BSE, futures, and options are not part of this list."""
    return [row for row in trade_universe(kite) if row.get("book") == "equity"]


def trade_universe(kite) -> list[dict]:
    """NSE large, mid, and small cap shares. Commodities, futures, and options are not included."""
    global _universe_cache
    now = time.monotonic()
    if _universe_cache and now - _universe_cache[0] < CACHE_SECONDS:
        return _universe_cache[1]
    allowed = listed_cap_symbols()
    rows = [row for row in _cash_rows(kite) if row["ticker"] in allowed]
    if not rows:
        raise SignalScanError("Kite returned no NSE large, mid, or small cap shares.")
    rows.sort(key=lambda row: (row["book"], row["ticker"]))
    _universe_cache = (now, rows)
    return rows


def _cash_rows(kite) -> list[dict]:
    rows = []
    seen = set()
    for instrument in _load_instruments(kite, "NSE"):
        if not isinstance(instrument, dict):
            continue
        if instrument.get("exchange") != "NSE" or instrument.get("instrument_type") != "EQ":
            continue
        if str(instrument.get("segment") or "NSE") != "NSE":
            continue
        symbol = str(instrument.get("tradingsymbol") or "").strip().upper()
        token = instrument.get("instrument_token")
        company = str(instrument.get("name") or symbol).strip() or symbol
        if not symbol or symbol in seen or token is None or not _regular_equity(symbol, company):
            continue
        seen.add(symbol)
        rows.append({
            "ticker": symbol,
            "company": company,
            "token": int(token),
            "exchange": "NSE",
            "instrument_type": "EQ",
            "book": "equity",
        })
    return rows


def _stock_derivative_rows(kite) -> list[dict]:
    futures = []
    options = []
    today = datetime.now(timezone.utc).date()
    for instrument in _load_instruments(kite, "NFO"):
        if not isinstance(instrument, dict) or instrument.get("exchange") != "NFO":
            continue
        kind = str(instrument.get("instrument_type") or "").upper()
        underlying = str(instrument.get("name") or "").strip().upper()
        symbol = str(instrument.get("tradingsymbol") or "").strip().upper()
        token = instrument.get("instrument_token")
        expiry = _as_date(instrument.get("expiry"))
        if not underlying or underlying in _INDEX_UNDERLYINGS or not symbol or token is None or expiry is None or expiry < today:
            continue
        row = {
            "ticker": symbol,
            "company": underlying,
            "token": int(token),
            "exchange": "NFO",
            "instrument_type": kind,
            "expiry": expiry,
        }
        if kind == "FUT":
            row["book"] = "stock_future"
            futures.append(row)
        elif kind in {"CE", "PE"}:
            row["book"] = "stock_option"
            options.append(row)
    return futures + _front_expiry(options)


def _front_expiry(rows: list[dict]) -> list[dict]:
    nearest: dict[str, date] = {}
    for row in rows:
        current = nearest.get(row["company"])
        if current is None or row["expiry"] < current:
            nearest[row["company"]] = row["expiry"]
    return [row for row in rows if row["expiry"] == nearest.get(row["company"])]


_CAP_LISTS = (
    (
        "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv",
        "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv",
    ),
    (
        "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
        "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    ),
    (
        "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
        "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
    ),
)
_cap_cache: Optional[tuple[float, set[str]]] = None


def listed_cap_symbols() -> set[str]:
    """NSE large, mid, and small cap symbols: Nifty 100, Midcap 150, and Smallcap 250."""
    global _cap_cache
    now = time.monotonic()
    if _cap_cache and now - _cap_cache[0] < CACHE_SECONDS:
        return set(_cap_cache[1])
    found: set[str] = set()
    for urls in _CAP_LISTS:
        found.update(_index_symbols(urls))
    if len(found) < 400:
        if _cap_cache:
            return set(_cap_cache[1])
        raise SignalScanError("The large, mid, and small cap lists could not be loaded.")
    _cap_cache = (now, found)
    return set(found)


def _index_symbols(urls: tuple[str, str]) -> set[str]:
    for url in urls:
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


def build_scanner_payload(kite, budget_seconds: Optional[float] = None) -> dict:
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
        from kite_app.desk_progress import note_fill

        note_fill(len(constituents), len(constituents), False)
        return _public_payload(constituents, saved)
    if recorded_all and not within_ttl:
        saved = {}

    from kite_app.desk_progress import note_fill

    nifty100 = _nifty_tickers(load_nifty100)
    nifty50 = load_nifty50_symbols()
    filled = sum(1 for row in constituents if (saved.get(row["ticker"]) or {}).get("candles"))
    note_fill(filled, len(constituents), True)
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
        filled += 1
        note_fill(filled, len(constituents), True)
        saved[symbol] = {
            "symbol": symbol,
            "company_name": constituent["company"],
            "instrument_token": int(token),
            "exchange": str(constituent.get("exchange") or "NSE").upper() or "NSE",
            "instrument_type": "EQ",
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
        "exchange": str(constituent.get("exchange") or "NSE").upper() or "NSE",
        "instrument_type": "EQ",
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


def _read_cache() -> Optional[dict]:
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


def _read_s3_cache() -> Optional[dict]:
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


def _candle_row(raw: dict) -> Optional[dict]:
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
