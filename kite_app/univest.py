"""Parse Univest notification text and forward a structured signal to the algo webhook."""

from __future__ import annotations

import logging
import os
import re
from collections import deque
from datetime import datetime

import requests

logger = logging.getLogger("kite_app.univest")

_inbox: deque[dict] = deque(maxlen=50)
_attempts: deque[dict] = deque(maxlen=30)

SYMBOL = r"[A-Z][A-Z0-9&-]{1,19}"
STOPWORDS = {
    "BUY", "SELL", "EXIT", "BOOK", "CNC", "MIS", "NRML", "NSE", "BSE",
    "SL", "TGT", "TGTS", "TARGET", "TARGETS", "ENTRY", "CMP", "UNIVEST",
    "INTRADAY", "DELIVERY", "POSITIONAL", "PROFIT", "PARTIAL", "TRAIL",
    "STOP", "LOSS", "PRICE", "STOCK", "SHARE", "CALL", "ABOVE", "BELOW",
    "RANGE", "ALERT", "TRADE", "T1", "T2", "T3", "RS", "INR", "EQ", "FUT",
    "HOLD", "ZONE", "COST", "BOOKED", "PROFIT",
}


class UnivestParseError(Exception):
    """The notification is not a usable trade alert."""


def parse_univest(text: str) -> dict:
    raw = (text or "").replace("\u00a0", " ").strip()
    compact = re.sub(r"\s+", " ", raw)
    if len(compact) < 3:
        raise UnivestParseError("Notification text is empty.")

    transaction_type, signal_kind = _action(compact)
    symbol = _symbol(raw, transaction_type)
    if symbol is None:
        raise UnivestParseError(
            "No NSE ticker found. Include a symbol such as TATAMOTORS or RELIANCE."
        )

    entry_low, entry_high, entry_price = _entry(compact, transaction_type, symbol)
    if entry_price is None:
        raise UnivestParseError("No entry or booking price found.")

    targets = _targets(compact)
    payload = {
        "symbol": symbol,
        "transaction_type": transaction_type,
        "entry_price": entry_price,
        "stop_loss": _stop_loss(compact),
        "target": targets[0] if targets else None,
        "source": "univest",
        "product": _product(compact),
        "targets": targets,
        "signal_kind": signal_kind,
    }
    if entry_low is not None and entry_high is not None:
        payload["entry_low"] = entry_low
        payload["entry_high"] = entry_high
    return payload


def remember(payload: dict) -> None:
    _inbox.appendleft(payload)


def recent_signals() -> list[dict]:
    return list(_inbox)


def record_attempt(text: str, payload: dict | None, error: str | None) -> None:
    preview = re.sub(r"\s+", " ", text or "").strip()[:300]
    _attempts.appendleft(
        {
            "received_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "accepted": payload is not None,
            "error": error,
            "preview": preview,
            "payload": payload,
        }
    )


def recent_attempts() -> list[dict]:
    return list(_attempts)


def dispatch(payload: dict) -> dict:
    """Store the signal and POST it when the algo URL is another service.

    A same-process HTTP call would block the only server worker, so the local
    inbox is written directly. A failed remote webhook is logged and does not raise.
    """
    remember(payload)
    url = os.environ.get("UNIVEST_ALGO_WEBHOOK_URL", "http://127.0.0.1:8010/api/kite/algo/signal")
    if _is_local_inbox(url):
        logger.info(
            "Univest signal stored symbol=%s side=%s kind=%s",
            payload.get("symbol"),
            payload.get("transaction_type"),
            payload.get("signal_kind"),
        )
        return {"dispatched": True, "status_code": 200}
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Univest webhook was not delivered: %s", exc.__class__.__name__)
        return {"dispatched": False, "error": exc.__class__.__name__}
    logger.info(
        "Univest signal dispatched symbol=%s side=%s kind=%s",
        payload.get("symbol"),
        payload.get("transaction_type"),
        payload.get("signal_kind"),
    )
    return {"dispatched": True, "status_code": response.status_code}


def _is_local_inbox(url: str) -> bool:
    normalized = url.rstrip("/").lower()
    return normalized.endswith("/api/kite/algo/signal") and (
        "127.0.0.1" in normalized or "localhost" in normalized
    )


def _action(text: str) -> tuple[str, str]:
    if re.search(r"book\s+\d+\s*%|partial\s+profit|book\s+profit", text, re.IGNORECASE):
        return "SELL", "partial_book"
    if re.search(r"\b(exit|square[\s-]?off)\b", text, re.IGNORECASE):
        return "SELL", "exit"
    match = re.search(r"\b(BUY|SELL)\b", text, re.IGNORECASE)
    if not match:
        raise UnivestParseError("No BUY or SELL action found.")
    return match.group(1).upper(), "entry"


def _symbol(text: str, action: str) -> str | None:
    upper = text.upper()
    patterns = (
        rf"(?:NSE|SYMBOL|STOCK|SCRIP)\s*[:\-]\s*({SYMBOL})",
        rf"\(({SYMBOL})\)",
        rf"\b(?:IN|FOR)\s+({SYMBOL})\b",
        rf"\b{action}\b\s*[:\-]?\s*({SYMBOL})",
        rf"\b({SYMBOL})\b\s*[:\-]?\s*\b{action}\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, upper):
            symbol = match.group(1)
            if symbol not in STOPWORDS:
                return symbol
    return None


def _entry(text: str, action: str, symbol: str) -> tuple[float | None, float | None, float | None]:
    ranged = re.search(
        r"(?:entry(?:\s+price)?|cmp|price|zone|above|at|@)\s*[:\-]?\s*(?:rs\.?\s*)?"
        r"(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(?:rs\.?\s*)?(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if ranged:
        low = float(ranged.group(1))
        high = float(ranged.group(2))
        if low > high:
            low, high = high, low
        return low, high, round((low + high) / 2, 2)

    single = re.search(
        r"(?:entry(?:\s+price)?|cmp|price|above|at|@)\s*[:\-]?\s*(?:rs\.?\s*)?(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if single:
        price = round(float(single.group(1)), 2)
        return None, None, price

    bare = re.search(
        rf"\b{action}\b\s+{re.escape(symbol)}\s+(?:@|at\s+)?(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if bare:
        return None, None, round(float(bare.group(1)), 2)
    return None, None, None


def _stop_loss(text: str) -> float | None:
    match = re.search(
        r"(?:stop[\s-]*loss|stoploss|s\.?\s*l\.?)\s*[:\-]?\s*(?:rs\.?\s*)?(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None
    return round(float(match.group(1)), 2)


def _targets(text: str) -> list[float]:
    found: list[float] = []
    block = re.search(r"(?:targets?|tgts?)\s*[:\-]\s*([0-9./,\sand]+)", text, re.IGNORECASE)
    if block:
        found.extend(float(item) for item in re.findall(r"\d+(?:\.\d+)?", block.group(1)))
    for match in re.finditer(
        r"\b(?:t(?:arget)?|tgt)\s*[123]?\s*[:\-]?\s*(?:rs\.?\s*)?(\d+(?:\.\d+)?)",
        text,
        re.IGNORECASE,
    ):
        found.append(float(match.group(1)))
    unique: list[float] = []
    for price in found:
        rounded = round(price, 2)
        if rounded not in unique:
            unique.append(rounded)
    return unique


def _product(text: str) -> str | None:
    if re.search(r"\bMIS\b|\bintraday\b", text, re.IGNORECASE):
        return "MIS"
    if re.search(r"\bNRML\b", text, re.IGNORECASE):
        return "NRML"
    if re.search(r"\bCNC\b|\bdelivery\b|\bpositional\b|\bswing\b", text, re.IGNORECASE):
        return "CNC"
    return None
