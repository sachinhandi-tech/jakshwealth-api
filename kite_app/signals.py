"""Daily moving-average crossover scan. Supports Nifty 100 or all 3080 NSE equities. Uses Kite candles."""

from __future__ import annotations

import csv
import io
import time
from datetime import date, datetime, timedelta
from typing import Optional

import requests
from kiteconnect.exceptions import KiteException, TokenException

NIFTY100_CSV_URL = "https://www.niftyindices.com/IndexConstituent/ind_nifty100list.csv"
NIFTY100_CSV_FALLBACK = "https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv"
CACHE_SECONDS = 6 * 60 * 60
REQUEST_GAP_SECONDS = 0.35
# API Gateway closes the HTTP request at about 29 seconds. Stop before that.
SCAN_BUDGET_SECONDS = 22

_constituent_cache: Optional[tuple[float, list[dict]]] = None
_token_cache: Optional[tuple[float, dict[str, int]]] = None


class SignalScanError(Exception):
    """Scanner problem safe to show in the UI."""


MA_TYPES = ("sma", "ema", "wma")


def simple_moving_average(closes: list[float], window: int) -> list[Optional[float]]:
    averages: list[Optional[float]] = [None] * len(closes)
    if window <= 0:
        return averages
    running = 0.0
    for index, price in enumerate(closes):
        running += price
        if index >= window:
            running -= closes[index - window]
        if index >= window - 1:
            averages[index] = running / window
    return averages


def exponential_moving_average(closes: list[float], window: int) -> list[Optional[float]]:
    """EMA seeded with the first SMA. The smoothing factor is 2 / (window + 1)."""
    averages: list[Optional[float]] = [None] * len(closes)
    if window <= 0 or len(closes) < window:
        return averages
    seed = sum(closes[:window]) / window
    averages[window - 1] = seed
    weight = 2 / (window + 1)
    previous = seed
    for index in range(window, len(closes)):
        previous = closes[index] * weight + previous * (1 - weight)
        averages[index] = previous
    return averages


def weighted_moving_average(closes: list[float], window: int) -> list[Optional[float]]:
    """WMA gives the newest close weight `window` and the oldest close weight 1."""
    averages: list[Optional[float]] = [None] * len(closes)
    if window <= 0:
        return averages
    weight_total = window * (window + 1) / 2
    for index in range(window - 1, len(closes)):
        weighted = 0.0
        start = index - window + 1
        for offset in range(window):
            weighted += closes[start + offset] * (offset + 1)
        averages[index] = weighted / weight_total
    return averages


def moving_average(closes: list[float], window: int, ma_type: str) -> list[Optional[float]]:
    if ma_type == "ema":
        return exponential_moving_average(closes, window)
    if ma_type == "wma":
        return weighted_moving_average(closes, window)
    return simple_moving_average(closes, window)


def latest_crossover(
    candles: list[dict],
    short_window: int,
    long_window: int,
    lookback_days: int,
    ma_type: str = "sma",
    short_type: Optional[str] = None,
    long_type: Optional[str] = None,
    trend_window: int = 0,
) -> Optional[dict]:
    """Return the newest cross of the fast average over the slow average."""
    fast_type = short_type or ma_type
    slow_type = long_type or ma_type
    if long_window <= short_window or lookback_days < 1 or len(candles) < long_window + 1:
        return None
    if fast_type not in MA_TYPES or slow_type not in MA_TYPES:
        return None
    closes = [float(candle["close"]) for candle in candles]
    short_line = moving_average(closes, short_window, fast_type)
    long_line = moving_average(closes, long_window, slow_type)
    trend_line = simple_moving_average(closes, trend_window) if trend_window >= 2 else None
    start = max(long_window, len(candles) - lookback_days)
    found = None
    for index in range(start, len(candles)):
        previous_short = short_line[index - 1]
        previous_long = long_line[index - 1]
        current_short = short_line[index]
        current_long = long_line[index]
        if None in (previous_short, previous_long, current_short, current_long):
            continue
        previous_gap = previous_short - previous_long
        current_gap = current_short - current_long
        if previous_gap <= 0 and current_gap > 0:
            crossover_type = "bullish"
        elif previous_gap >= 0 and current_gap < 0:
            crossover_type = "bearish"
        else:
            continue
        found = _row(candles, closes, index, crossover_type, current_short, current_long, trend_line)
    return found


def latest_price_cross(candles: list[dict], window: int, lookback_days: int) -> Optional[dict]:
    """Return the newest cross of the daily close through an SMA."""
    if window < 2 or lookback_days < 1 or len(candles) < window + 1:
        return None
    closes = [float(candle["close"]) for candle in candles]
    trend_line = simple_moving_average(closes, window)
    start = max(window, len(candles) - lookback_days)
    found = None
    for index in range(start, len(candles)):
        previous_trend = trend_line[index - 1]
        current_trend = trend_line[index]
        if previous_trend is None or current_trend is None:
            continue
        previous_gap = closes[index - 1] - previous_trend
        current_gap = closes[index] - current_trend
        if previous_gap <= 0 and current_gap > 0:
            crossover_type = "bullish"
        elif previous_gap >= 0 and current_gap < 0:
            crossover_type = "bearish"
        else:
            continue
        found = _row(candles, closes, index, crossover_type, closes[index], current_trend, trend_line)
    return found


def _row(
    candles: list[dict],
    closes: list[float],
    index: int,
    crossover_type: str,
    fast_value: float,
    slow_value: float,
    trend_line: Optional[list[Optional[float]]],
) -> dict:
    trend_value = trend_line[index] if trend_line else None
    if trend_value is None:
        trend_bias = None
    elif closes[index] > trend_value:
        trend_bias = "above"
    else:
        trend_bias = "below"
    return {
        "crossover_type": crossover_type,
        "crossover_date": _as_date(candles[index]["date"]).isoformat(),
        "close": round(closes[index], 2),
        "short_sma": round(fast_value, 2),
        "long_sma": round(slow_value, 2),
        "trend_sma": None if trend_value is None else round(trend_value, 2),
        "trend_bias": trend_bias,
    }


def parse_nifty100_csv(text: str) -> list[dict]:
    rows = []
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    for raw in reader:
        columns = {(key or "").strip().lower(): (value or "").strip() for key, value in raw.items()}
        symbol = columns.get("symbol", "")
        company = columns.get("company name", "")
        series = columns.get("series", "EQ")
        if not symbol or not company or series not in ("", "EQ"):
            continue
        rows.append({"ticker": symbol, "company": company})
    if len(rows) < 50:
        raise SignalScanError("The Nifty 100 constituent file did not contain the expected symbols.")
    return rows


def scan_nifty100(
    kite,
    short_window: int,
    long_window: int,
    lookback_days: int,
    max_stocks: int,
    ma_type: str = "sma",
    short_type: Optional[str] = None,
    long_type: Optional[str] = None,
    trend_window: int = 0,
    scan_mode: str = "crossover",
    budget_seconds: Optional[float] = None,
    scan_all_nse: bool = False,
) -> dict:
    deadline = time.monotonic() + (SCAN_BUDGET_SECONDS if budget_seconds is None else budget_seconds)
    tokens = nse_equity_tokens(kite)
    constituents = load_nse_all_stocks(tokens) if scan_all_nse else load_nifty100()
    end = datetime.now()
    history_window = max(long_window, trend_window)
    calendar_days = int((lookback_days + history_window + 5) * 1.8) + 10
    start = end - timedelta(days=calendar_days)
    signals = []
    skipped = 0
    scanned = 0

    for offset, constituent in enumerate(constituents):
        if time.monotonic() >= deadline:
            break
        if offset:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(REQUEST_GAP_SECONDS, remaining))
        token = tokens.get(constituent["ticker"])
        if token is None:
            skipped += 1
            continue
        try:
            candles = kite.historical_data(token, start, end, "day")
        except TokenException:
            raise
        except KiteException:
            skipped += 1
            continue
        scanned += 1
        if scan_mode == "price":
            crossover = latest_price_cross(candles, long_window, lookback_days)
        else:
            crossover = latest_crossover(
                candles,
                short_window,
                long_window,
                lookback_days,
                ma_type,
                short_type,
                long_type,
                trend_window,
            )
        if crossover is None:
            continue
        signals.append({**constituent, **crossover})

    signals.sort(key=lambda row: (row["crossover_date"], row["ticker"]), reverse=True)
    limited = signals[:max_stocks]
    for rank, row in enumerate(limited, start=1):
        row["rank"] = rank
    return {
        "scan_mode": scan_mode,
        "ma_type": short_type or ma_type,
        "short_type": short_type or ma_type,
        "long_type": "sma" if scan_mode == "price" else (long_type or ma_type),
        "trend_window": long_window if scan_mode == "price" else trend_window,
        "short_window": short_window,
        "long_window": long_window,
        "lookback_days": lookback_days,
        "universe": len(constituents),
        "scanned": scanned,
        "skipped": skipped,
        "signals": limited,
    }


def load_nifty100() -> list[dict]:
    global _constituent_cache
    now = time.monotonic()
    if _constituent_cache and now - _constituent_cache[0] < CACHE_SECONDS:
        return _constituent_cache[1]
    last_error = "The Nifty 100 list could not be downloaded."
    for url in (NIFTY100_CSV_URL, NIFTY100_CSV_FALLBACK):
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "text/csv,*/*"},
                timeout=8,
            )
            response.raise_for_status()
            rows = parse_nifty100_csv(response.text)
        except SignalScanError as exc:
            last_error = str(exc)
            continue
        except requests.RequestException as exc:
            last_error = f"The Nifty 100 list could not be downloaded ({exc.__class__.__name__})."
            continue
        _constituent_cache = (now, rows)
        return rows
    raise SignalScanError(last_error)


def load_nse_all_stocks(tokens: dict[str, int]) -> list[dict]:
    """Extract all NSE equities from the tokens dictionary."""
    constituents = []
    for symbol in sorted(tokens.keys()):
        constituents.append({"ticker": symbol, "company": symbol})
    if not constituents:
        raise SignalScanError("No NSE equity instruments found.")
    return constituents


def nse_equity_tokens(kite) -> dict[str, int]:
    global _token_cache
    now = time.monotonic()
    if _token_cache and now - _token_cache[0] < CACHE_SECONDS:
        return _token_cache[1]
    try:
        instruments = kite.instruments("NSE")
    except TokenException:
        raise
    except KiteException as exc:
        raise SignalScanError("Kite could not load NSE instruments.") from exc
    tokens = {}
    for instrument in instruments:
        if instrument.get("exchange") == "NSE" and instrument.get("instrument_type") == "EQ":
            symbol = str(instrument.get("tradingsymbol") or "").strip()
            token = instrument.get("instrument_token")
            if symbol and token is not None:
                tokens[symbol] = int(token)
    if not tokens:
        raise SignalScanError("Kite returned no NSE equity instruments.")
    _token_cache = (now, tokens)
    return tokens


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])
