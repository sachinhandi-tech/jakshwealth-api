"""Live buy-GTT placement. A confirmed request places one NSE CNC buy GTT on Kite."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from kiteconnect.exceptions import KiteException, TokenException

from kite_app.signals import SignalScanError

IST = ZoneInfo("Asia/Kolkata")
CREATED_MESSAGE = "Buy GTT placed on Kite. Stoploss planned after buy execution."
READY_MESSAGE = "Ready for buy GTT placement."
ACTIVE_GTT_MESSAGE = "Skipped: buy GTT already active."
TRIGGER_GTT_MESSAGE = "Skipped: GTT already active for this buy trigger."
DAY_ORDER_MESSAGE = "Skipped: day BUY order already exists."
WAITING_MESSAGE = "Waiting for LTP."
MISSING_BUY_MESSAGE = "Buy price is not available for this row."
TICK_MESSAGE = "Trigger price should be a multiple of tick size."
BELOW_LTP_MESSAGE = "Buy trigger must be below the last price."
_RECENT_SECONDS = 120.0
_LOCK = threading.RLock()
_RECENT: dict[str, tuple[str, float]] = {}


class GttRejected(Exception):
    """The request cannot place a GTT."""


def clear_recent_placements() -> None:
    with _LOCK:
        _RECENT.clear()


def gtt_state(kite, orders: list[dict]) -> list[dict]:
    account = _read_account(kite)
    return [_evaluate(kite, order, account, create=False) for order in orders]


def live_gtt(kite, orders: list[dict], confirm_live: Optional[bool], platform_user_id=None, zerodha_user_id=None) -> list[dict]:
    if confirm_live is not True:
        rejected = []
        for order in orders:
            row = _blank(_symbol(str(order.get("symbol") or "")), _optional_decimal(order.get("last_price")))
            row["message"] = "confirm_live must be true to place a buy GTT."
            rejected.append(row)
        _record_attempts(rejected, confirm_live, platform_user_id, zerodha_user_id)
        raise GttRejected("confirm_live must be true to place a buy GTT.")
    account = _read_account(kite)
    rows = []
    for order in orders:
        try:
            row = _evaluate(kite, order, account, create=True)
        except TokenException as exc:
            row = _blank(_symbol(str(order.get("symbol") or "")), _optional_decimal(order.get("last_price")))
            row["message"] = f"Unable to place buy GTT: {_broker_message(exc)}"
            _record_attempts([row], confirm_live, platform_user_id, zerodha_user_id)
            raise
        _record_attempts([row], confirm_live, platform_user_id, zerodha_user_id)
        rows.append(row)
    return rows


def _evaluate(kite, order: dict, account: dict, create: bool) -> dict:
    symbol = _symbol(str(order.get("symbol") or ""))
    last_price = _optional_decimal(order.get("last_price"))
    buy_raw = _optional_decimal(order.get("buy_price"))
    row = _blank(symbol, last_price)
    if not symbol or buy_raw is None or buy_raw <= 0:
        row.update(account_state="invalid", buy_status="not_available", stoploss_status="not_available", message=MISSING_BUY_MESSAGE)
        return row
    tick = account["ticks"].get(symbol)
    if tick is None or tick <= 0:
        row.update(account_state="invalid", buy_status="failed", message=TICK_MESSAGE)
        return row
    try:
        buy_price = round_to_tick(buy_raw, tick)
        stoploss = round_to_tick(buy_price * Decimal("0.95"), tick)
    except (ArithmeticError, ValueError):
        row.update(account_state="invalid", buy_status="failed", message=TICK_MESSAGE)
        return row
    if not _is_tick_multiple(buy_price, tick) or not _is_tick_multiple(stoploss, tick):
        row.update(account_state="invalid", buy_status="failed", buy_price=_number(buy_price), stoploss=_number(stoploss), tick_size=_number(tick), message=TICK_MESSAGE)
        return row
    row.update(buy_price=_number(buy_price), stoploss=_number(stoploss), tick_size=_number(tick), stoploss_status="planned_after_buy")
    blocked = _block_reason(symbol, buy_price, account)
    if blocked is not None:
        row.update(blocked)
        return row
    if last_price is None or last_price <= 0:
        row.update(account_state="waiting", buy_status="waiting_for_ltp", message=WAITING_MESSAGE)
        return row
    if not create:
        row.update(account_state="clear", buy_status="ready", message=READY_MESSAGE)
        return row
    if buy_price >= last_price:
        row.update(account_state="invalid", buy_status="failed", message=BELOW_LTP_MESSAGE)
        return row
    try:
        trigger_id, created = _place_buy(kite, symbol, buy_price, last_price)
    except TokenException:
        raise
    except KiteException as exc:
        row.update(account_state="clear", buy_status="failed", message=f"Unable to place buy GTT: {_broker_message(exc)}")
        return row
    if not created:
        row.update(
            account_state="already_active",
            buy_status="already_active",
            active_buy_trigger_id=trigger_id,
            buy_trigger_id=trigger_id,
            message=ACTIVE_GTT_MESSAGE,
        )
        return row
    if not trigger_id:
        row.update(account_state="clear", buy_status="failed", message="Unable to place buy GTT: Kite did not return a trigger id.")
        return row
    row.update(
        account_state="clear",
        buy_status="success",
        buy_trigger_id=trigger_id,
        message=CREATED_MESSAGE,
    )
    return row


def _record_attempts(rows: list[dict], confirm_live, platform_user_id, zerodha_user_id) -> None:
    from kite_app.trading_store import record_gtt_attempt

    prefix = "Unable to place buy GTT: "
    for row in rows:
        message = str(row.get("message") or "")
        error = message[len(prefix):] if message.startswith(prefix) else None
        record_gtt_attempt(
            platform_user_id=platform_user_id,
            zerodha_user_id=zerodha_user_id,
            row=row,
            confirm_live=confirm_live,
            kite_error_text=error,
        )


def _place_buy(kite, symbol: str, buy_price: Decimal, last_price: Decimal) -> tuple[str, bool]:
    with _LOCK:
        try:
            listed = kite.get_gtts() or []
        except TokenException:
            raise
        except KiteException as exc:
            raise SignalScanError("Kite account state could not be read.") from exc
        existing = _buy_gtts(listed).get(symbol)
        if existing is not None:
            _RECENT.pop(symbol, None)
            return existing["id"], False
        matched = _trigger_match(listed, symbol, buy_price)
        if matched is not None:
            return matched, False
        recent = _recent_unlocked(symbol)
        if recent is not None:
            return recent, False
        result = kite.place_gtt(
            trigger_type="single",
            tradingsymbol=symbol,
            exchange="NSE",
            trigger_values=[_number(buy_price)],
            last_price=_number(last_price),
            orders=[{
                "transaction_type": "BUY",
                "quantity": 1,
                "price": _number(buy_price),
                "order_type": "LIMIT",
                "product": "CNC",
            }],
        )
        trigger_id = _trigger_id(result)
        if trigger_id:
            _RECENT[symbol] = (trigger_id, time.monotonic())
        return trigger_id, True


def round_to_tick(price: Decimal, tick: Decimal) -> Decimal:
    if tick <= 0:
        raise ValueError("Tick size must be positive.")
    steps = (price / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return (steps * tick).quantize(tick)


def _block_reason(symbol: str, buy_price: Decimal, account: dict) -> Optional[dict]:
    recent = _recent_id(symbol)
    if recent is not None:
        return {
            "account_state": "already_active",
            "buy_status": "already_active",
            "active_buy_trigger_id": recent,
            "buy_trigger_id": recent,
            "message": ACTIVE_GTT_MESSAGE,
        }
    real = account["buy_gtts"].get(symbol)
    if real is not None:
        return {
            "account_state": "already_active",
            "buy_status": "already_active",
            "active_buy_trigger_id": real["id"],
            "buy_trigger_id": real["id"],
            "message": ACTIVE_GTT_MESSAGE,
        }
    matched = _trigger_match(account["gtts"], symbol, buy_price)
    if matched is not None:
        return {
            "account_state": "already_active",
            "buy_status": "already_active",
            "active_buy_trigger_id": matched,
            "buy_trigger_id": matched,
            "message": TRIGGER_GTT_MESSAGE,
        }
    day_order = account["day_orders"].get(symbol)
    if day_order is not None:
        return {
            "account_state": "day_buy_order_exists",
            "buy_status": "blocked",
            "day_buy_order_id": day_order["id"],
            "day_buy_order_status": day_order["status"],
            "message": DAY_ORDER_MESSAGE,
        }
    quantity = account["quantities"].get(symbol, 0)
    if quantity > 0:
        stoploss = account["sell_gtts"].get(symbol)
        return {
            "account_state": "position_exists",
            "buy_status": "blocked",
            "position_quantity": quantity,
            "active_stoploss_trigger_id": None if stoploss is None else stoploss,
            "stoploss_trigger_id": None if stoploss is None else stoploss,
            "message": f"Skipped: existing position/holding quantity is {quantity}.",
        }
    if buy_price <= 0:
        return {"account_state": "invalid", "buy_status": "not_available", "message": MISSING_BUY_MESSAGE}
    return None


def _read_account(kite) -> dict:
    try:
        gtts = kite.get_gtts() or []
        orders = kite.orders() or []
        positions = kite.positions() or {}
        holdings = kite.holdings() or []
        instruments = kite.instruments("NSE") or []
    except TokenException:
        raise
    except KiteException as exc:
        raise SignalScanError("Kite account state could not be read.") from exc
    if not isinstance(gtts, list) or not isinstance(orders, list) or not isinstance(holdings, list) or not isinstance(instruments, list):
        raise SignalScanError("Kite account state could not be read.")
    return {
        "gtts": gtts,
        "ticks": _tick_sizes(instruments),
        "buy_gtts": _buy_gtts(gtts),
        "sell_gtts": _sell_gtts(gtts),
        "day_orders": _day_buy_orders(orders),
        "quantities": _open_quantities(positions, holdings),
    }


def _tick_sizes(instruments: list) -> dict[str, Decimal]:
    ticks = {}
    for instrument in instruments:
        if not isinstance(instrument, dict):
            continue
        if instrument.get("exchange") != "NSE" or instrument.get("instrument_type") != "EQ":
            continue
        symbol = _symbol(str(instrument.get("tradingsymbol") or ""))
        tick = _optional_decimal(instrument.get("tick_size"))
        if symbol and tick is not None and tick > 0:
            ticks[symbol] = tick
    return ticks


def _buy_gtts(gtts: list) -> dict[str, dict]:
    found = {}
    for item in gtts:
        parsed = _gtt(item)
        if parsed is not None and "BUY" in parsed["sides"]:
            found[parsed["symbol"]] = parsed
    return found


def _sell_gtts(gtts: list) -> dict[str, str]:
    found = {}
    for item in gtts:
        parsed = _gtt(item)
        if parsed is not None and "SELL" in parsed["sides"]:
            found[parsed["symbol"]] = parsed["id"]
    return found


def _trigger_match(gtts: list, symbol: str, buy_price: Decimal) -> Optional[str]:
    for item in gtts:
        parsed = _gtt(item)
        if parsed is None or parsed["symbol"] != symbol:
            continue
        if any(trigger == buy_price for trigger in parsed["triggers"]):
            return parsed["id"]
    return None


def _gtt(item: dict) -> Optional[dict]:
    if not isinstance(item, dict) or str(item.get("status") or "").lower() != "active":
        return None
    condition = item.get("condition") or {}
    symbol = _symbol(str(condition.get("tradingsymbol") or ""))
    orders = item.get("orders") or []
    sides = {
        str(order.get("transaction_type") or "").upper()
        for order in orders
        if isinstance(order, dict)
    }
    if not symbol or not sides:
        return None
    triggers = []
    for value in condition.get("trigger_values") or []:
        trigger = _optional_decimal(value)
        if trigger is not None:
            triggers.append(trigger)
    return {"symbol": symbol, "id": str(item.get("id")), "sides": sides, "triggers": triggers}


def _day_buy_orders(orders: list) -> dict[str, dict]:
    today = datetime.now(IST).date()
    found = {}
    for order in orders:
        if not isinstance(order, dict):
            continue
        if str(order.get("exchange") or "").upper() != "NSE":
            continue
        if str(order.get("transaction_type") or "").upper() != "BUY":
            continue
        if str(order.get("product") or "").upper() not in {"CNC", "DELIVERY"}:
            continue
        status = str(order.get("status") or "").upper()
        if status in {"CANCELLED", "REJECTED"}:
            continue
        if not _is_today(order.get("order_timestamp") or order.get("exchange_timestamp"), today):
            continue
        symbol = _symbol(str(order.get("tradingsymbol") or ""))
        if symbol and symbol not in found:
            found[symbol] = {"id": str(order.get("order_id") or ""), "status": status}
    return found


def _open_quantities(positions, holdings: list) -> dict[str, int]:
    quantities: dict[str, int] = {}
    net = positions.get("net") if isinstance(positions, dict) else []
    for position in net or []:
        if not isinstance(position, dict):
            continue
        symbol = _symbol(str(position.get("tradingsymbol") or ""))
        quantity = _whole(position.get("quantity"))
        if symbol and quantity > 0:
            quantities[symbol] = max(quantities.get(symbol, 0), quantity)
    for holding in holdings:
        if not isinstance(holding, dict):
            continue
        symbol = _symbol(str(holding.get("tradingsymbol") or ""))
        quantity = _whole(holding.get("quantity")) + _whole(holding.get("t1_quantity"))
        if symbol and quantity > 0:
            quantities[symbol] = max(quantities.get(symbol, 0), quantity)
    return quantities


def _blank(symbol: str, last_price: Optional[Decimal]) -> dict:
    return {
        "symbol": symbol,
        "quantity": 1,
        "buy_price": None,
        "stoploss": None,
        "tick_size": None,
        "last_price": None if last_price is None else _number(last_price),
        "account_state": "invalid",
        "position_quantity": 0,
        "active_buy_trigger_id": None,
        "active_stoploss_trigger_id": None,
        "day_buy_order_id": None,
        "day_buy_order_status": None,
        "buy_status": "not_placed",
        "buy_trigger_id": None,
        "stoploss_status": "not_placed",
        "stoploss_trigger_id": None,
        "message": "",
    }


def _recent_id(symbol: str) -> Optional[str]:
    with _LOCK:
        return _recent_unlocked(symbol)


def _recent_unlocked(symbol: str) -> Optional[str]:
    found = _RECENT.get(symbol)
    if found is None:
        return None
    trigger_id, stamp = found
    if time.monotonic() - stamp > _RECENT_SECONDS:
        _RECENT.pop(symbol, None)
        return None
    return trigger_id


def _trigger_id(result) -> str:
    value = result.get("trigger_id") if isinstance(result, dict) else result
    text = str(value or "").strip()
    if not text or text.lower() == "none":
        return ""
    return text


def _broker_message(exc: Exception) -> str:
    message = str(getattr(exc, "message", None) or exc)
    lowered = message.lower()
    if "access_token" in lowered or "api_secret" in lowered:
        return "Zerodha rejected the GTT."
    return message or "Zerodha rejected the GTT."


def _is_tick_multiple(price: Decimal, tick: Decimal) -> bool:
    return tick > 0 and price % tick == 0


def _is_today(value, today) -> bool:
    if isinstance(value, datetime):
        stamp = value if value.tzinfo else value.replace(tzinfo=IST)
        return stamp.astimezone(IST).date() == today
    text = str(value or "").strip()
    return len(text) >= 10 and text[:10] == today.isoformat()


def _optional_decimal(value) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    except (ArithmeticError, ValueError):
        return None
    if not decimal.is_finite():
        return None
    return decimal


def _whole(value) -> int:
    decimal = _optional_decimal(value)
    if decimal is None:
        return 0
    return int(decimal)


def _number(value: Decimal) -> float:
    return float(format(value, "f"))


def _symbol(value: str) -> str:
    return value.strip().upper()
