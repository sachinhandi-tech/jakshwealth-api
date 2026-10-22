"""GTT attempts, order history, trades, and postback receipts. One database transaction each."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from kite_app.persistence import trading_session
from kite_app.trading_models import GttAttempt, OrderCommand, OrderEvent, RejectedPostback, TradeRow

logger = logging.getLogger("kite_app.trading")

_ORDER_FIELDS = (
    "placed_by", "order_id", "exchange_order_id", "parent_order_id", "status",
    "status_message", "status_message_raw", "order_timestamp", "exchange_update_timestamp",
    "exchange_timestamp", "variety", "modified", "exchange", "tradingsymbol",
    "instrument_token", "order_type", "transaction_type", "validity", "product",
    "quantity", "disclosed_quantity", "price", "trigger_price", "average_price",
    "filled_quantity", "pending_quantity", "cancelled_quantity", "market_protection",
    "tag", "guid",
)
_SOURCES = {"postback", "orders_list", "order_history"}
_RECONCILED: set[tuple[str, str]] = set()

# Kite documents websocket text messages of type "order" as the postback payload.
# persist_socket_order stores that payload with source postback.


def persist_socket_order(payload: dict, platform_user_id=None) -> bool:
    """Store a Kite websocket order postback. The payload is the postback object."""
    if not isinstance(payload, dict):
        return False
    if payload.get("checksum"):
        raw = json.dumps(payload).encode("utf-8")
        return bool(accept_postback(raw, platform_user_id=platform_user_id)["checksum_valid"])
    return insert_order_event(
        "postback",
        payload,
        platform_user_id=platform_user_id,
        checksum_valid=None,
        raw=payload,
    )


def submit_order_command(kite, action: str, parameters: dict, *, platform_user_id=None, zerodha_user_id=None):
    """Call place, modify, or cancel and store the command. Placement is not a fill."""
    methods = {"place": "place_order", "modify": "modify_order", "cancel": "cancel_order"}
    if action not in methods:
        raise ValueError("action must be place, modify, or cancel")
    try:
        result = getattr(kite, methods[action])(**parameters)
    except Exception as exc:
        record_order_command(
            action=action,
            parameters=parameters,
            order_id=None,
            http_failure_body=str(exc),
            platform_user_id=platform_user_id,
            zerodha_user_id=zerodha_user_id,
        )
        raise
    order_id = result.get("order_id") if isinstance(result, dict) else None
    record_order_command(
        action=action,
        parameters=parameters,
        order_id=None if order_id is None else str(order_id),
        http_failure_body=None,
        platform_user_id=platform_user_id,
        zerodha_user_id=zerodha_user_id,
    )
    return result


def record_gtt_attempt(
    *,
    platform_user_id,
    zerodha_user_id,
    row: dict,
    confirm_live: Optional[bool],
    kite_error_text: Optional[str] = None,
) -> Optional[uuid.UUID]:
    if not _enabled():
        return None
    attempt_id = uuid.uuid4()
    sent = row.get("buy_status") not in {None, "not_available"} and row.get("buy_price") is not None
    db = trading_session()
    try:
        db.add(GttAttempt(
            attempt_id=attempt_id,
            platform_user_id=platform_user_id,
            zerodha_user_id=None if zerodha_user_id is None else str(zerodha_user_id),
            tradingsymbol=row.get("symbol") or None,
            exchange="NSE" if sent else None,
            trigger_type="single" if sent else None,
            trigger_value=None if row.get("buy_price") is None else str(row.get("buy_price")),
            last_price=None if row.get("last_price") is None else str(row.get("last_price")),
            transaction_type="BUY" if sent else None,
            quantity=1 if sent else None,
            price=None if row.get("buy_price") is None else str(row.get("buy_price")),
            order_type="LIMIT" if sent else None,
            product="CNC" if sent else None,
            confirm_live=confirm_live,
            trigger_id=None if not row.get("buy_trigger_id") else str(row.get("buy_trigger_id")),
            requested_at=datetime.now(timezone.utc),
            outcome=str(row.get("message") or ""),
            kite_error_text=kite_error_text,
        ))
        db.commit()
    finally:
        db.close()
    logger.info("gtt attempt_id=%s trigger_id=%s", attempt_id, row.get("buy_trigger_id"))
    return attempt_id


def record_order_command(*, action: str, parameters: dict, order_id: Optional[str], http_failure_body: Optional[str], platform_user_id=None, zerodha_user_id=None) -> uuid.UUID:
    """Store a place, modify, or cancel request. The order is not marked complete here."""
    command_id = uuid.uuid4()
    db = trading_session()
    try:
        db.add(OrderCommand(
            command_id=command_id,
            platform_user_id=platform_user_id,
            zerodha_user_id=None if zerodha_user_id is None else str(zerodha_user_id),
            action=action,
            variety=_text(parameters.get("variety")),
            exchange=_text(parameters.get("exchange")),
            tradingsymbol=_text(parameters.get("tradingsymbol")),
            transaction_type=_text(parameters.get("transaction_type")),
            quantity=_text(parameters.get("quantity")),
            product=_text(parameters.get("product")),
            order_type=_text(parameters.get("order_type")),
            price=_text(parameters.get("price")),
            trigger_price=_text(parameters.get("trigger_price")),
            validity=_text(parameters.get("validity")),
            disclosed_quantity=_text(parameters.get("disclosed_quantity")),
            tag=_text(parameters.get("tag")),
            order_id=order_id,
            http_failure_body=http_failure_body,
            requested_at=datetime.now(timezone.utc),
        ))
        db.commit()
    finally:
        db.close()
    logger.info("order command_id=%s order_id=%s", command_id, order_id)
    return command_id


def insert_order_event(source: str, payload: dict, *, platform_user_id=None, checksum_valid: Optional[bool], raw: Optional[dict]) -> bool:
    if source not in _SOURCES:
        return False
    values = {name: _text(payload.get(name)) for name in _ORDER_FIELDS}
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else None
    zerodha_user_id = _text(payload.get("user_id")) or _text(payload.get("placed_by"))
    db = trading_session()
    try:
        filters = [
            OrderEvent.source == source,
            _eq(OrderEvent.order_id, values["order_id"]),
            _eq(OrderEvent.order_timestamp, values["order_timestamp"]),
            _eq(OrderEvent.status, values["status"]),
            _eq(OrderEvent.filled_quantity, values["filled_quantity"]),
            _eq(OrderEvent.guid, values["guid"]),
        ]
        if db.scalar(select(OrderEvent.event_id).where(*filters)) is not None:
            return False
        event_id = uuid.uuid4()
        db.add(OrderEvent(
            event_id=event_id,
            source=source,
            platform_user_id=platform_user_id,
            zerodha_user_id=zerodha_user_id,
            received_at=datetime.now(timezone.utc),
            checksum_valid=checksum_valid,
            meta=meta,
            raw_json=raw,
            **values,
        ))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return False
    finally:
        db.close()
    logger.info("order event_id=%s order_id=%s source=%s", event_id, values["order_id"], source)
    return True


def insert_trade(source: str, payload: dict, *, platform_user_id=None) -> bool:
    trade_id = _text(payload.get("trade_id"))
    order_id = _text(payload.get("order_id"))
    if source not in {"trades_list", "order_trades"} or not trade_id or not order_id:
        return False
    db = trading_session()
    try:
        found = db.scalar(
            select(TradeRow.trade_row_id).where(TradeRow.trade_id == trade_id, TradeRow.order_id == order_id)
        )
        if found is not None:
            return False
        db.add(TradeRow(
            trade_row_id=uuid.uuid4(),
            source=source,
            platform_user_id=platform_user_id,
            received_at=datetime.now(timezone.utc),
            trade_id=trade_id,
            order_id=order_id,
            exchange=_text(payload.get("exchange")),
            tradingsymbol=_text(payload.get("tradingsymbol")),
            instrument_token=_text(payload.get("instrument_token")),
            product=_text(payload.get("product")),
            average_price=_text(payload.get("average_price")),
            quantity=_text(payload.get("quantity")),
            exchange_order_id=_text(payload.get("exchange_order_id")),
            transaction_type=_text(payload.get("transaction_type")),
            fill_timestamp=_text(payload.get("fill_timestamp")),
            order_timestamp=_text(payload.get("order_timestamp")),
            exchange_timestamp=_text(payload.get("exchange_timestamp")),
            raw_json=payload if isinstance(payload, dict) else None,
        ))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return False
    finally:
        db.close()
    logger.info("trade order_id=%s", order_id)
    return True


def accept_postback(raw: bytes, platform_user_id=None) -> dict:
    """Verify SHA-256(order_id + order_timestamp + api_secret). Commit before returning."""
    text = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        _reject(text)
        return {"checksum_valid": False}
    if not isinstance(payload, dict):
        _reject(text)
        return {"checksum_valid": False}
    secret = _api_secret()
    expected = hashlib.sha256(
        f"{payload.get('order_id', '')}{payload.get('order_timestamp', '')}{secret}".encode("utf-8")
    ).hexdigest()
    supplied = str(payload.get("checksum") or "")
    if not secret or not hmac.compare_digest(expected, supplied):
        _reject(text)
        return {"checksum_valid": False}
    insert_order_event("postback", payload, platform_user_id=platform_user_id, checksum_valid=True, raw=payload)
    return {"checksum_valid": True}


def reconcile_book(kite, platform_user_id, zerodha_user_id, token_date: str) -> None:
    """Pull today's orders and trades while this token_date is still the current one."""
    key = (str(platform_user_id), token_date)
    if key in _RECONCILED:
        return
    orders = kite.orders() or []
    for item in orders:
        if isinstance(item, dict):
            insert_order_event("orders_list", item, platform_user_id=platform_user_id, checksum_valid=None, raw=item)
    seen = []
    for item in orders:
        if isinstance(item, dict) and item.get("order_id"):
            seen.append(str(item["order_id"]))
    for order_id in dict.fromkeys(seen):
        history = kite.order_history(order_id) or []
        for item in history:
            if isinstance(item, dict):
                insert_order_event("order_history", item, platform_user_id=platform_user_id, checksum_valid=None, raw=item)
        logger.info("order_id=%s", order_id)
    for item in kite.trades() or []:
        if isinstance(item, dict):
            insert_trade("trades_list", item, platform_user_id=platform_user_id)
    _RECONCILED.add(key)


def _reject(raw_body: str) -> None:
    db = trading_session()
    try:
        db.add(RejectedPostback(
            rejected_id=uuid.uuid4(),
            received_at=datetime.now(timezone.utc),
            raw_body=raw_body,
        ))
        db.commit()
    finally:
        db.close()


def _enabled() -> bool:
    if os.environ.get("TRADING_DATABASE_URL", "").strip() or os.environ.get("DATABASE_URL", "").strip():
        return True
    from kite_app.models import load_platform_config

    load_platform_config()
    return bool(os.environ.get("DATABASE_URL", "").strip())


def _api_secret() -> str:
    from kite_app.models import load_platform_config

    load_platform_config()
    return os.environ.get("KITE_API_SECRET", "").strip()


def _eq(column, value):
    if value is None:
        return column.is_(None)
    return column == value


def _text(value) -> Optional[str]:
    if value is None or isinstance(value, bool):
        if isinstance(value, bool):
            return "true" if value else "false"
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)
