"""Live buy-GTT placement. A confirmed request places one cash-equity CNC buy GTT on Kite."""

from __future__ import annotations

import threading
import time
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from kiteconnect.exceptions import KiteException, TokenException

from kite_app.signals import SignalScanError

IST = ZoneInfo("Asia/Kolkata")
EQUITY_BUDGET_INR = Decimal("100000")
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
    account = _read_account(kite, orders)
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
    account = _read_account(kite, orders)
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


def arm_exit(kite, orders: list[dict], confirm_live: Optional[bool], platform_user_id=None, zerodha_user_id=None) -> list[dict]:
    """Place one NSE CNC two-leg sell GTT after the buy is in holdings."""
    if confirm_live is not True:
        raise GttRejected("confirm_live must be true to place a stoploss and target GTT.")
    account = _read_account(kite, orders)
    rows = []
    for order in orders:
        row = _arm_one(kite, order, account)
        _record_attempts([row], confirm_live, platform_user_id, zerodha_user_id)
        rows.append(row)
    return rows


def _arm_one(kite, order: dict, account: dict) -> dict:
    symbol = _symbol(str(order.get("symbol") or ""))
    last_price = _optional_decimal(order.get("last_price"))
    stop_raw = _optional_decimal(order.get("stoploss"))
    target_raw = _optional_decimal(order.get("target"))
    row = _blank(symbol, last_price)
    if not symbol or last_price is None or last_price <= 0 or stop_raw is None or target_raw is None:
        row.update(account_state="invalid", stoploss_status="not_available", message="Stoploss and target need a last price.")
        return row
    contract = _contract(account, order, symbol)
    if contract is None:
        row.update(account_state="invalid", stoploss_status="failed", message=TICK_MESSAGE)
        return row
    tick = contract["tick"]
    stop = round_to_tick(stop_raw, tick)
    target = round_to_tick(target_raw, tick)
    held = account["quantities"].get(symbol, 0)
    quantity = _sell_quantity(contract, last_price, held)
    row.update(stoploss=_number(stop), target=_number(target), tick_size=_number(tick), quantity=quantity, exchange=contract["exchange"], product=_product(contract))
    if held < 1:
        row.update(account_state="waiting", stoploss_status="planned_after_buy", message="Stoploss GTT waits until the buy is in holdings.")
        return row
    existing = account["sell_gtts"].get(symbol)
    if existing is not None:
        row.update(
            account_state="position_exists",
            position_quantity=held,
            stoploss_status="already_active",
            stoploss_trigger_id=existing,
            message="Sell GTT already active.",
        )
        return row
    if quantity < 1:
        row.update(account_state="invalid", stoploss_status="failed", message=_size_message(contract, last_price))
        return row
    if not (stop < last_price < target):
        row.update(account_state="invalid", stoploss_status="failed", message="Stoploss must be below the last price and the target above it.")
        return row
    product = _product(contract)
    try:
        result = kite.place_gtt(
            trigger_type="two-leg",
            tradingsymbol=symbol,
            exchange=contract["exchange"],
            trigger_values=[_number(stop), _number(target)],
            last_price=_number(last_price),
            orders=[
                {"transaction_type": "SELL", "quantity": quantity, "price": _number(stop), "order_type": "LIMIT", "product": product},
                {"transaction_type": "SELL", "quantity": quantity, "price": _number(target), "order_type": "LIMIT", "product": product},
            ],
        )
    except TokenException:
        raise
    except KiteException as exc:
        row.update(account_state="position_exists", position_quantity=held, stoploss_status="failed", message=f"Unable to place sell GTT: {_broker_message(exc)}")
        return row
    trigger_id = _trigger_id(result)
    if not trigger_id:
        row.update(stoploss_status="failed", message="Unable to place sell GTT: Kite did not return a trigger id.")
        return row
    row.update(
        account_state="position_exists",
        position_quantity=held,
        stoploss_status="success",
        stoploss_trigger_id=trigger_id,
        message=f"Stoploss and 2R target placed as one {contract['exchange']} {product} sell GTT for quantity {quantity}.",
    )
    return row


def _evaluate(kite, order: dict, account: dict, create: bool) -> dict:
    symbol = _symbol(str(order.get("symbol") or ""))
    last_price = _optional_decimal(order.get("last_price"))
    buy_raw = _optional_decimal(order.get("buy_price"))
    row = _blank(symbol, last_price)
    if not symbol or buy_raw is None or buy_raw <= 0:
        row.update(account_state="invalid", buy_status="not_available", stoploss_status="not_available", message=MISSING_BUY_MESSAGE)
        return row
    contract = _contract(account, order, symbol)
    if contract is None:
        row.update(account_state="invalid", buy_status="failed", message=TICK_MESSAGE)
        return row
    tick = contract["tick"]
    try:
        buy_price = round_to_tick(buy_raw, tick)
        stoploss = round_to_tick(buy_price * Decimal("0.95"), tick)
    except (ArithmeticError, ValueError):
        row.update(account_state="invalid", buy_status="failed", message=TICK_MESSAGE)
        return row
    if not _is_tick_multiple(buy_price, tick) or not _is_tick_multiple(stoploss, tick):
        row.update(account_state="invalid", buy_status="failed", buy_price=_number(buy_price), stoploss=_number(stoploss), tick_size=_number(tick), message=TICK_MESSAGE)
        return row
    quantity, size_message = _buy_quantity(contract, buy_price)
    row.update(
        buy_price=_number(buy_price),
        stoploss=_number(stoploss),
        tick_size=_number(tick),
        stoploss_status="planned_after_buy",
        quantity=quantity,
        exchange=contract["exchange"],
        product=_product(contract),
    )
    if quantity < 1:
        row.update(account_state="invalid", buy_status="failed", message=size_message)
        return row
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
        trigger_id, created = _place_buy(kite, symbol, contract["exchange"], _product(contract), quantity, buy_price, last_price)
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


def _place_buy(kite, symbol: str, exchange: str, product: str, quantity: int, buy_price: Decimal, last_price: Decimal) -> tuple[str, bool]:
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
            exchange=exchange,
            trigger_values=[_number(buy_price)],
            last_price=_number(last_price),
            orders=[{
                "transaction_type": "BUY",
                "quantity": quantity,
                "price": _number(buy_price),
                "order_type": "LIMIT",
                "product": product,
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


def _read_account(kite, orders: list[dict]) -> dict:
    exchanges = []
    for order in orders:
        exchange = str(order.get("exchange") or "NSE").strip().upper() or "NSE"
        if exchange not in exchanges:
            exchanges.append(exchange)
    try:
        gtts = kite.get_gtts() or []
        day_orders = kite.orders() or []
        positions = kite.positions() or {}
        holdings = kite.holdings() or []
        instruments = []
        for exchange in exchanges:
            batch = kite.instruments(exchange) or []
            if not isinstance(batch, list):
                raise SignalScanError("Kite account state could not be read.")
            instruments.extend(batch)
    except TokenException:
        raise
    except KiteException as exc:
        raise SignalScanError("Kite account state could not be read.") from exc
    if not isinstance(gtts, list) or not isinstance(day_orders, list) or not isinstance(holdings, list):
        raise SignalScanError("Kite account state could not be read.")
    return {
        "gtts": gtts,
        "contracts": _contracts(instruments),
        "buy_gtts": _buy_gtts(gtts),
        "sell_gtts": _sell_gtts(gtts),
        "day_orders": _day_buy_orders(day_orders),
        "quantities": _open_quantities(positions, holdings),
    }


def share_quantity(price: Decimal) -> int:
    """Whole shares whose cost stays within one lakh rupees."""
    if price <= 0:
        return 0
    return int(EQUITY_BUDGET_INR // price)


def _contract(account: dict, order: dict, symbol: str) -> Optional[dict]:
    exchange = str(order.get("exchange") or "NSE").strip().upper() or "NSE"
    return account["contracts"].get((exchange, symbol))


def _contracts(instruments: list) -> dict[tuple[str, str], dict]:
    found = {}
    for instrument in instruments:
        if not isinstance(instrument, dict):
            continue
        exchange = str(instrument.get("exchange") or "").upper()
        symbol = _symbol(str(instrument.get("tradingsymbol") or ""))
        tick = _optional_decimal(instrument.get("tick_size"))
        if not symbol or tick is None or tick <= 0:
            continue
        found[(exchange, symbol)] = {
            "exchange": exchange,
            "tick": tick,
            "lot_size": _whole(instrument.get("lot_size")),
            "instrument_type": str(instrument.get("instrument_type") or "").upper(),
        }
    return found


def _product(contract: dict) -> str:
    if contract["exchange"] in {"NSE", "BSE"} and contract["instrument_type"] in {"", "EQ"}:
        return "CNC"
    return "NRML"


def _buy_quantity(contract: dict, price: Decimal) -> tuple[int, str]:
    exchange = contract["exchange"]
    kind = contract["instrument_type"]
    if exchange in {"NSE", "BSE"} and kind in {"", "EQ"}:
        quantity = share_quantity(price)
        if quantity < 1:
            return 0, "One lakh rupees does not buy one share at this price."
        return quantity, ""
    if (exchange == "NFO" and kind in {"FUT", "CE", "PE"}) or (exchange == "MCX" and kind == "FUT"):
        if contract["lot_size"] < 1:
            return 0, "Kite did not return a lot size for this contract."
        return contract["lot_size"], ""
    return 0, "This contract is not sent to Kite."


def _sell_quantity(contract: dict, price: Decimal, held: int) -> int:
    exchange = contract["exchange"]
    kind = contract["instrument_type"]
    if exchange in {"NSE", "BSE"} and kind in {"", "EQ"}:
        return min(held, share_quantity(price))
    if (exchange == "NFO" and kind in {"FUT", "CE", "PE"}) or (exchange == "MCX" and kind == "FUT"):
        lot = contract["lot_size"]
        if lot < 1 or held < lot:
            return 0
        return lot
    return 0


def _size_message(contract: dict, price: Decimal) -> str:
    if contract["exchange"] in {"NSE", "BSE"} and contract["instrument_type"] in {"", "EQ"}:
        if share_quantity(price) < 1:
            return "One lakh rupees does not buy one share at this price."
        return "The holding is smaller than one share."
    if contract["lot_size"] < 1:
        return "Kite did not return a lot size for this contract."
    return "The position is smaller than one lot."


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
        exchange = str(order.get("exchange") or "").upper()
        product = str(order.get("product") or "").upper()
        if exchange in {"NSE", "BSE"} and product not in {"CNC", "DELIVERY"}:
            continue
        if exchange in {"NFO", "MCX"} and product != "NRML":
            continue
        if exchange not in {"NSE", "BSE", "NFO", "MCX"}:
            continue
        if str(order.get("transaction_type") or "").upper() != "BUY":
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
        "quantity": 0,
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
