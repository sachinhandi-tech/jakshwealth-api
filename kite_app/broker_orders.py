"""Place Univest calls on Zerodha. Only the entry order is sent."""

from __future__ import annotations

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

from kiteconnect.exceptions import KiteException

_IST = ZoneInfo("Asia/Kolkata")
_placed: set[str] = set()


class OrderRejected(Exception):
    """The call cannot be sent as a Zerodha order."""


def execute_univest_orders(kite, signal: dict) -> dict:
    """Send LIMIT entries for a parsed Univest call. Stop and target stay on the signal."""
    if os.environ.get("UNIVEST_AUTO_TRADE", "1").strip().lower() in {"0", "false", "no"}:
        return {"placed": False, "orders": [], "error": "Automatic orders are turned off."}
    try:
        orders = build_orders(
            signal,
            _book(kite, signal, "NFO"),
            _book(kite, signal, "NSE"),
            _equity_quantity(),
            _book(kite, signal, "MCX"),
            _book(kite, signal, "BFO"),
        )
    except OrderRejected as exc:
        return {"placed": False, "orders": [], "error": str(exc)}
    placed: list[dict] = []
    today = datetime.now(_IST).date().isoformat()
    for order in orders:
        key = f"{today}|{order['exchange']}|{order['tradingsymbol']}|{order['transaction_type']}|{order['quantity']}|{order['price']}"
        if key in _placed:
            placed.append({**_public(order), "order_id": None, "duplicate": True})
            continue
        try:
            order_id = kite.place_order(
                variety="regular",
                validity="DAY",
                tag="UNIVEST",
                **order,
            )
        except KiteException as exc:
            return {
                "placed": bool(placed),
                "orders": placed,
                "error": _safe_message(exc),
            }
        _placed.add(key)
        placed.append({**_public(order), "order_id": str(order_id), "duplicate": False})
    return {"placed": True, "orders": placed, "error": None}


def build_orders(
    signal: dict,
    nfo: list[dict],
    nse: list[dict],
    equity_quantity: int,
    mcx: list[dict] | None = None,
    bfo: list[dict] | None = None,
) -> list[dict]:
    """Resolve Kite symbols and quantities. Does not call Zerodha."""
    books = {"NFO": nfo, "NSE": nse, "MCX": mcx or [], "BFO": bfo or []}
    product = signal.get("product") or "CNC"
    built: list[dict] = []
    for leg in signal.get("legs") or []:
        exchange = leg.get("exchange") or signal.get("segment") or "NSE"
        if exchange != "NSE":
            exchange, row = _resolve_derivative(books, leg)
            ratio = int(leg.get("ratio") or 1)
            quantity = int(row["lot_size"]) * ratio
            _check_card_lot(leg.get("lot_size"), int(row["lot_size"]))
            tradingsymbol = str(row["tradingsymbol"])
        else:
            tradingsymbol = _resolve_equity(nse, str(leg.get("tradingsymbol") or leg.get("underlying") or signal["symbol"]))
            quantity = int(leg["quantity"]) if leg.get("quantity") else equity_quantity
            if quantity < 1:
                raise OrderRejected("Stock call has no quantity.")
        price = leg.get("price")
        if price is None:
            raise OrderRejected("Call has no limit price.")
        built.append(
            {
                "exchange": exchange,
                "tradingsymbol": tradingsymbol,
                "transaction_type": leg["transaction_type"],
                "quantity": quantity,
                "product": product,
                "order_type": "LIMIT",
                "price": round(float(price), 2),
            }
        )
    if not built:
        raise OrderRejected("Call has no orders.")
    return built


def _book(kite, signal: dict, exchange: str) -> list[dict]:
    needed = set()
    for leg in signal.get("legs") or []:
        needed.update(leg.get("exchanges") or [leg.get("exchange")])
    if exchange not in needed:
        return []
    return list(kite.instruments(exchange) or [])


def _resolve_derivative(books: dict[str, list[dict]], leg: dict) -> tuple[str, dict]:
    exchanges = list(leg.get("exchanges") or [leg.get("exchange") or "NFO"])
    last = OrderRejected(f"No Zerodha contract for {leg.get('underlying')} {leg.get('instrument_type')}.")
    for exchange in exchanges:
        try:
            return exchange, _match_contract(books.get(exchange) or [], leg)
        except OrderRejected as exc:
            last = exc
    raise last


def _match_contract(rows: list[dict], leg: dict) -> dict:
    wanted_type = str(leg.get("instrument_type") or "")
    underlying = str(leg.get("underlying") or "")
    strike = leg.get("strike")
    matches = []
    for row in rows:
        if str(row.get("name") or "").upper() != underlying:
            continue
        if str(row.get("instrument_type") or "") != wanted_type:
            continue
        expiry = row.get("expiry")
        if not isinstance(expiry, date):
            continue
        if expiry.day != leg.get("expiry_day") or expiry.month != leg.get("expiry_month"):
            continue
        if wanted_type in {"CE", "PE"} and float(row.get("strike") or 0) != float(strike):
            continue
        matches.append(row)
    if not matches:
        raise OrderRejected(f"No Zerodha contract for {underlying} {wanted_type}.")
    matches.sort(key=lambda row: row["expiry"])
    return matches[0]


def _resolve_equity(rows: list[dict], symbol: str) -> str:
    wanted = symbol.upper()
    for row in rows:
        if str(row.get("tradingsymbol") or "").upper() == wanted and str(row.get("instrument_type") or "") == "EQ":
            return str(row["tradingsymbol"])
    plain = wanted.split("-", 1)[0]
    for row in rows:
        if str(row.get("tradingsymbol") or "").upper() == plain and str(row.get("instrument_type") or "") == "EQ":
            return str(row["tradingsymbol"])
    raise OrderRejected(f"No NSE symbol for {symbol}.")


def _check_card_lot(card_lot: int | None, exchange_lot: int) -> None:
    if card_lot is None:
        return
    if int(card_lot) != exchange_lot:
        raise OrderRejected(f"Lot size {card_lot} does not match the Zerodha lot {exchange_lot}.")


def _instruments(kite, exchange: str) -> list[dict]:
    return list(kite.instruments(exchange) or [])


def _equity_quantity() -> int:
    raw = os.environ.get("UNIVEST_EQUITY_QUANTITY", "1").strip()
    try:
        quantity = int(raw)
    except ValueError:
        return 1
    return quantity if quantity > 0 else 1


def _public(order: dict) -> dict:
    return {
        "exchange": order["exchange"],
        "tradingsymbol": order["tradingsymbol"],
        "transaction_type": order["transaction_type"],
        "quantity": order["quantity"],
        "product": order["product"],
        "order_type": order["order_type"],
        "price": order["price"],
    }


def _safe_message(exc: KiteException) -> str:
    message = str(getattr(exc, "message", None) or exc)
    if "access_token" in message.lower() or "api_secret" in message.lower():
        return "Zerodha rejected the order."
    return message or "Zerodha rejected the order."
