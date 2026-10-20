"""Breakout and retest scan. Same rules as the desk Algo Signals scanner."""

from __future__ import annotations

from datetime import date, datetime, timedelta

VOLUME_LOOKBACK = 20
VOLUME_MULTIPLIER = 3
PRICE_LOOKBACK = 20
MAX_BREAKOUT_AGE = 20
MIDPOINT_TOLERANCE = 1


def triggered_rows(stocks: list[dict]) -> list[dict]:
    """Keep the candle rows the desk scanner will show."""
    found = []
    for stock in stocks:
        candles = stock.get("candles") or []
        if not candles:
            continue
        setup = _scan_stock({
            "symbol": stock.get("symbol") or "",
            "company_name": stock.get("company_name") or "",
            "instrument_token": stock.get("instrument_token"),
            "candles": candles,
        })
        if setup is not None:
            found.append(stock)
    return found


def scan_breakouts(stocks: list[dict]) -> dict:
    setups = []
    for stock in stocks:
        setup = _scan_stock(stock)
        if setup is not None:
            setups.append(setup)
    setups.sort(key=lambda item: (item["days_since"], abs(item["distance_from_midpoint"])))
    return {"scanned": len(stocks), "setups": setups}


def normalize_candles(raw: list) -> list[dict]:
    candles = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        candle_date = _format_date(item.get("date", item.get("time", item.get("timestamp"))))
        open_price = _number(item.get("open"))
        high = _number(item.get("high"))
        low = _number(item.get("low"))
        close = _number(item.get("close"))
        volume = _number(item.get("volume"))
        if None in (candle_date, open_price, high, low, close, volume):
            continue
        candles.append({
            "date": candle_date,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })
    candles.sort(key=lambda item: item["date"])
    return candles


def self_test_fixture() -> list[dict]:
    """One known breakout and one quiet stock. Dates match the desk fixture."""
    triggered = _stock("INFY", _with_breakout(_history(45), 40, 100))
    quiet = _stock("QUIET", _history(45))
    return [triggered, quiet]


def _scan_stock(stock: dict) -> dict | None:
    candles = stock["candles"]
    if len(candles) < PRICE_LOOKBACK + 5:
        return None
    latest_index = len(candles) - 1
    earliest = max(VOLUME_LOOKBACK, PRICE_LOOKBACK, latest_index - MAX_BREAKOUT_AGE)
    for index in range(latest_index - 1, earliest - 1, -1):
        setup = _accept_breakout(stock, candles, index)
        if setup is not None:
            return setup
    return None


def _accept_breakout(stock: dict, candles: list[dict], index: int) -> dict | None:
    candidate = candles[index]
    volume_window = candles[index - VOLUME_LOOKBACK:index]
    price_window = candles[index - PRICE_LOOKBACK:index]
    if len(volume_window) < VOLUME_LOOKBACK or len(price_window) < PRICE_LOOKBACK:
        return None
    average_volume = sum(item["volume"] for item in volume_window) / len(volume_window)
    if average_volume <= 0:
        return None
    previous_high = max(item["high"] for item in price_window)
    if not candidate["close"] > candidate["open"]:
        return None
    if candidate["volume"] < average_volume * VOLUME_MULTIPLIER:
        return None
    if not candidate["close"] > previous_high:
        return None
    after = candles[index + 1:]
    max_price_after = max(item["high"] for item in after)
    if not max_price_after > candidate["high"]:
        return None
    midpoint = (candidate["high"] + candidate["low"]) / 2
    if not midpoint > 0:
        return None
    current_price = candles[-1]["close"]
    distance = ((current_price - midpoint) / midpoint) * 100
    days_since = len(candles) - 1 - index
    if abs(distance) > MIDPOINT_TOLERANCE or days_since > MAX_BREAKOUT_AGE:
        return None
    breakout_close = candidate["close"]
    return {
        "symbol": stock["symbol"],
        "company_name": stock["company_name"],
        "instrument_token": stock["instrument_token"],
        "current_price": current_price,
        "breakout_date": candidate["date"],
        "b_index": index,
        "days_since": days_since,
        "breakout_low": candidate["low"],
        "breakout_high": candidate["high"],
        "midpoint": midpoint,
        "distance_from_midpoint": distance,
        "vol_multiple": candidate["volume"] / average_volume,
        "prev_high": previous_high,
        "max_price_after": max_price_after,
        "return_from_close_to_sub_high": ((max_price_after - breakout_close) / breakout_close) * 100,
        "retracement_high": ((max_price_after - current_price) / max_price_after) * 100,
    }


def _history(count: int) -> list[dict]:
    return [_candle(index) for index in range(count)]


def _with_breakout(candles: list[dict], index: int, latest_close: float) -> list[dict]:
    nxt = [dict(item) for item in candles]
    nxt[index] = _candle(index, open_price=100, high=110, low=90, close=108, volume=4000)
    latest = len(nxt) - 1
    nxt[latest] = _candle(latest, open_price=latest_close, high=130, low=latest_close - 1, close=latest_close, volume=1000)
    if latest - 1 != index:
        nxt[latest - 1] = _candle(latest - 1, high=120, close=100, open_price=100)
    return nxt


def _stock(symbol: str, candles: list[dict]) -> dict:
    return {
        "symbol": symbol,
        "company_name": f"{symbol} Ltd",
        "instrument_token": 1,
        "candles": candles,
    }


def _candle(index: int, open_price: float = 100, high: float = 101, low: float = 99, close: float = 100, volume: float = 1000) -> dict:
    return {
        "date": (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _format_date(value) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return None


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if value == value else None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if parsed != parsed:
        return None
    return parsed
