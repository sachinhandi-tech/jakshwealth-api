"""Turn a Univest advisory card into one or more order legs."""

from __future__ import annotations

import re

from kite_app.univest import UnivestParseError, parse_univest

_MONTHS = {
    "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AUG": 8,
    "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DEC": 12,
}
_MONTH = r"JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC"


def parse_alerts(text: str) -> list[dict]:
    """Parse every Univest card in the text. The sample cards are the layout, not a symbol list."""
    raw = _normalize(text)
    found: list[dict] = []
    for chunk in _chunks(raw):
        card = _futures_card(chunk) or _options_card(chunk) or _stock_card(chunk)
        if card is not None:
            found.append(card)
    if found:
        return found
    return [_plain(raw)]


def parse_alert(text: str) -> dict:
    """Parse the first Univest card, or a short BUY/SELL notification."""
    alerts = parse_alerts(text)
    return alerts[0]


def _plain(raw: str) -> dict:
    parsed = parse_univest(raw)
    parsed["segment"] = "NSE"
    parsed["legs"] = [
        {
            "transaction_type": parsed["transaction_type"],
            "underlying": parsed["symbol"],
            "tradingsymbol": parsed["symbol"],
            "exchange": "NSE",
            "instrument_type": "EQ",
            "quantity": None,
            "ratio": 1,
            "price": parsed["entry_price"],
            "stop_loss": parsed["stop_loss"],
            "target": parsed["target"],
        }
    ]
    return parsed


def _normalize(text: str) -> str:
    cleaned = (text or "").replace("\u00a0", " ").replace("₹", " ").replace("–", "-")
    return re.sub(r"(?<=\d),(?=\d)", "", cleaned)


def _chunks(text: str) -> list[str]:
    posted = re.split(r"(?=Posted\s*:)", text, flags=re.IGNORECASE)
    chunks: list[str] = []
    for part in posted:
        for piece in re.split(r"(?=Stock\s*-\s*)", part, flags=re.IGNORECASE):
            piece = piece.strip()
            if piece:
                chunks.append(piece)
    return chunks or [text]


def _futures_card(text: str) -> dict | None:
    match = re.search(
        rf"\b([A-Z][A-Z0-9&-]{{1,14}})\s+(\d{{1,2}})\s+({_MONTH})\s+FUT\b",
        text.upper(),
    )
    if match is None:
        return None
    underlying, day, month = match.group(1), int(match.group(2)), _MONTHS[match.group(3)]
    side = _side(text)
    price, low, high = _price_and_range(text, side)
    lot = _lot_size(text)
    if price is None or lot is None:
        raise UnivestParseError("Futures call needs a price and a lot size.")
    return _single(
        underlying=underlying,
        side=side,
        price=price,
        low=low,
        high=high,
        lot=lot,
        product="NRML",
        segment="NFO",
        exchanges=["NFO", "MCX", "BFO"],
        instrument_type="FUT",
        expiry_day=day,
        expiry_month=month,
        stop_loss=_price_level(text, "stop"),
        target=_price_level(text, "target"),
    )


def _options_card(text: str) -> dict | None:
    pattern = re.compile(
        rf"\b(BUY|SELL)\s+(\d{{1,2}})\s+({_MONTH})\s+(\d+(?:\.\d+)?)\s+(CE|PE)\s+(\d+)\s+(\d+(?:\.\d+)?)",
        re.IGNORECASE,
    )
    found = list(pattern.finditer(text))
    if not found:
        return None
    lot = _lot_size(text)
    if lot is None:
        raise UnivestParseError("Options call needs a lot size.")
    underlying = _option_underlying(text[: found[0].start()])
    exchanges = ["BFO", "NFO"] if underlying in {"SENSEX", "BANKEX"} else ["NFO", "BFO"]
    legs = []
    for match in found:
        side, day, month, strike, kind, ratio, price = match.groups()
        legs.append(
            {
                "transaction_type": side.upper(),
                "underlying": underlying,
                "exchange": exchanges[0],
                "exchanges": exchanges,
                "instrument_type": kind.upper(),
                "expiry_day": int(day),
                "expiry_month": _MONTHS[month.upper()],
                "strike": float(strike),
                "ratio": int(ratio),
                "lot_size": lot,
                "quantity": None,
                "price": round(float(price), 2),
                "stop_loss": None,
                "target": None,
            }
        )
    first = legs[0]
    return {
        "symbol": underlying,
        "transaction_type": first["transaction_type"],
        "entry_price": first["price"],
        "stop_loss": None,
        "target": None,
        "source": "univest",
        "product": "NRML",
        "segment": "NFO",
        "signal_kind": "entry",
        "targets": [],
        "legs": legs,
    }


def _stock_card(text: str) -> dict | None:
    if not re.search(r"long\s+term|med(?:ium)?\.?\s+term|short\s+term|duration", text, re.IGNORECASE):
        return None
    side = _side(text)
    symbol = _stock_symbol(text.upper(), side)
    price, low, high = _price_and_range(text, side)
    if symbol is None or price is None:
        raise UnivestParseError("Stock call needs a symbol and a price.")
    return _single(
        underlying=symbol,
        side=side,
        price=price,
        low=low,
        high=high,
        lot=None,
        product="CNC",
        segment="NSE",
        instrument_type="EQ",
        expiry_day=None,
        expiry_month=None,
        stop_loss=_price_level(text, "stop"),
        target=_price_level(text, "target"),
    )


def _single(
    *,
    underlying: str,
    side: str,
    price: float,
    low: float | None,
    high: float | None,
    lot: int | None,
    product: str,
    segment: str,
    instrument_type: str,
    expiry_day: int | None,
    expiry_month: int | None,
    stop_loss: float | None,
    target: float | None,
    exchanges: list[str] | None = None,
) -> dict:
    leg = {
        "transaction_type": side,
        "underlying": underlying,
        "tradingsymbol": underlying if segment == "NSE" else None,
        "exchange": segment,
        "exchanges": exchanges or [segment],
        "instrument_type": instrument_type,
        "expiry_day": expiry_day,
        "expiry_month": expiry_month,
        "strike": None,
        "ratio": 1,
        "lot_size": lot,
        "quantity": None,
        "price": price,
        "stop_loss": stop_loss,
        "target": target,
    }
    payload = {
        "symbol": underlying,
        "transaction_type": side,
        "entry_price": price,
        "stop_loss": stop_loss,
        "target": target,
        "source": "univest",
        "product": product,
        "segment": segment,
        "signal_kind": "entry",
        "targets": [target] if target is not None else [],
        "legs": [leg],
    }
    if low is not None and high is not None:
        payload["entry_low"] = low
        payload["entry_high"] = high
    return payload


def _side(text: str) -> str:
    match = re.search(r"\b(BUY|SELL)\b", text, re.IGNORECASE)
    if match is None:
        raise UnivestParseError("No BUY or SELL action found.")
    return match.group(1).upper()


def _lot_size(text: str) -> int | None:
    match = re.search(r"lot\s*size\s*[:\-]?\s*(\d+)", text, re.IGNORECASE)
    if match is None:
        return None
    return int(match.group(1))


def _price_and_range(text: str, side: str) -> tuple[float | None, float | None, float | None]:
    ranged = re.search(
        rf"\b{side}\b\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if ranged:
        price = round(float(ranged.group(1)), 2)
        low = float(ranged.group(2))
        high = float(ranged.group(3))
        if low > high:
            low, high = high, low
        return price, low, high
    single = re.search(rf"\b{side}\b\s+(\d+(?:\.\d+)?)", text, re.IGNORECASE)
    if single:
        return round(float(single.group(1)), 2), None, None
    labeled = re.search(
        r"(?:price|entry|cmp)\s*[:\-]?\s*(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if labeled:
        return round(float(labeled.group(1)), 2), None, None
    return None, None, None


def _price_level(text: str, kind: str) -> float | None:
    if re.search(rf"{kind}\s*loss\s+amount|{kind}\s+amount", text, re.IGNORECASE):
        return None
    match = re.search(
        rf"(?:{kind}[\s-]*loss|{kind})\s*[:\-]?\s*(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if match is None or match.group(1) in {"0", "0.0"}:
        return None
    return round(float(match.group(1)), 2)


def _option_underlying(head: str) -> str:
    upper = head.upper()
    for label, name in (
        ("BANK NIFTY", "BANKNIFTY"),
        ("BANKNIFTY", "BANKNIFTY"),
        ("FINNIFTY", "FINNIFTY"),
        ("MIDCPNIFTY", "MIDCPNIFTY"),
        ("NIFTY", "NIFTY"),
        ("SENSEX", "SENSEX"),
        ("BANKEX", "BANKEX"),
    ):
        if label in upper:
            return name
    skip = {
        "BUY", "SELL", "STRATEGY", "EXECUTE", "ALL", "RATIO", "ENTRY", "LTP",
        "LOT", "SIZE", "POSTED", "ACTION", "PRICE", "RANGE", "NEW", "ALERT",
    }
    tokens = re.findall(r"\b[A-Z][A-Z0-9&-]{1,19}\b", upper)
    for token in reversed(tokens):
        if token not in skip and token not in _MONTHS:
            return token
    raise UnivestParseError("Options call needs the underlying name.")


def _stock_symbol(upper: str, side: str) -> str | None:
    match = re.search(rf"\b([A-Z][A-Z0-9&-]{{1,19}})\b\s+\b{side}\b", upper)
    if match and match.group(1) not in {"STOCK", "TERM", "LONG", "MED", "SHORT", "NEW"}:
        return match.group(1)
    match = re.search(r"\b([A-Z][A-Z0-9&-]{1,19}(?:-BE|-BL|-BZ)?)\b", upper)
    if match and match.group(1) not in {"STOCK", "TERM", "LONG", "MED", "SHORT", "BUY", "SELL", "NEW"}:
        return match.group(1)
    return None
