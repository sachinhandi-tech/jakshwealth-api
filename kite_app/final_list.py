"""Final list. The HTTP call returns immediately. Screening and the model run behind it."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Optional

logger = logging.getLogger("kite_app.final_list")

_LOCK = threading.Lock()
_RUNNING = False
_WORKING = False
_FOCUS = ""
_BOOK = {"scanned": 0, "accepted": 0, "setups": [], "sell_calls": []}
_REVIEWS: dict[str, dict] = {}
_LAST_SCREEN = 0.0
_LAST_COUNT = -1
_RECORD: Optional[dict] = None
_SEEN: set[str] = set()
_REVIEW_QUEUED: set[str] = set()
_STAMP = ("ai_decision", "ai_checks", "ai_reason", "gtt_tradable", "reason")
_PASS_LIMIT = 80
_SLICE = 250


def begin_final_list(record: Optional[dict], launch: bool = True) -> dict:
    """Start the equity read if needed and return the lines the desk can show now."""
    if not record or not record.get("api_key") or not record.get("access_token"):
        _set_working(False, "Log in to Zerodha to read equities, stock futures, stock options, and commodity futures.")
        return public_snapshot()
    if launch:
        _launch(record)
    else:
        _set_working(True, _FOCUS or "Reading equities, stock futures, stock options, and commodity futures.")
    return public_snapshot()


def public_snapshot() -> dict:
    with _LOCK:
        book = {
            "scanned": _BOOK["scanned"],
            "accepted": _BOOK["accepted"],
            "setups": [dict(item) for item in _BOOK["setups"]],
            "sell_calls": [dict(item) for item in _BOOK["sell_calls"]],
            "working": _WORKING,
        }
        focus = _FOCUS
    lines = _progress_lines()
    if focus and focus not in lines:
        lines.append(focus)
    if not lines:
        lines = ["Reading equities, stock futures, stock options, and commodity futures."]
    activity = []
    for index, text in enumerate(lines[-5:]):
        active = book["working"] and index == len(lines[-5:]) - 1
        activity.append({"text": text, "state": "active" if active else "done"})
    book["activity"] = activity
    book["universe_note"] = activity[-1]["text"] if book["working"] else ""
    return book


def refresh_book() -> None:
    """Screen saved names and send new passes to the model, one name at a time."""
    global _LAST_SCREEN, _LAST_COUNT
    stocks = _load_stocks()
    now = time.monotonic()
    if len(stocks) == _LAST_COUNT and now - _LAST_SCREEN < 20:
        return
    _set_focus(f"Checking all three screens on {len(stocks)} saved names.")
    from kite_app.algo_layers import select_setups

    book = select_setups(stocks, review=False)
    _review_rows(book["setups"])
    _review_rows(book["sell_calls"])
    with _LOCK:
        _BOOK["scanned"] = book["scanned"]
        _BOOK["accepted"] = book["accepted"]
        _BOOK["setups"] = [dict(item) for item in book["setups"]]
        _BOOK["sell_calls"] = [dict(item) for item in book["sell_calls"]]
    approved = [str(item.get("symbol") or "") for item in book["setups"] if item.get("ai_decision") == "buy"]
    if approved:
        _set_focus(f"{', '.join(approved)} is approved and ready for a Zerodha buy GTT.")
    elif int(book["accepted"]):
        _set_focus(f"{int(book['accepted'])} names passed every screen. The model is reading filings, news, and lawsuits.")
    else:
        _set_focus("No saved name has passed all three screens yet.")
    _LAST_SCREEN = time.monotonic()
    _LAST_COUNT = len(stocks)


def _review_rows(rows: list[dict]) -> None:
    from kite_app.algo_review import review_setups

    for item in rows:
        saved = _REVIEWS.get(_review_key(item))
        if saved:
            item.update(saved)
            continue
        symbol = str(item.get("symbol") or "")
        _set_focus(f"Reading filings, news, and lawsuits for {symbol}.")
        review_setups([item])
        _REVIEWS[_review_key(item)] = {key: item.get(key) for key in _STAMP}
        if item.get("ai_decision") == "buy":
            _set_focus(f"{symbol} is approved. It is ready for a Zerodha buy GTT.")
        elif item.get("ai_decision") == "sell":
            _set_focus(f"{symbol} is a sell call. It is not sent as an order.")


def _load_stocks() -> list[dict]:
    from kite_app.algo_layers import combine_books
    from kite_app.scan_jobs import latest_crossover_signals
    from kite_app.scanner_data import cached_equity
    from kite_app.signals_cache import history_by_ticker

    signals = latest_crossover_signals()
    remembered = history_by_ticker([signal["symbol"] for signal in signals]) if signals else []
    return combine_books([], signals, [*cached_equity(), *remembered])


def _progress_lines() -> list[str]:
    from kite_app.desk_progress import fill_status, scan_status

    lines = []
    fill = fill_status()
    universe = int(fill.get("universe") or 0)
    if fill.get("active") and universe:
        lines.append(f"Saving prices and volume: {int(fill.get('saved') or 0)} of {universe} names.")
    labels = {
        "crossover": "Moving-average crossover",
        "price": "Long moving average",
    }
    books = {
        "equity": "Equities",
        "stock_future": "Stock futures",
        "stock_option": "Stock options",
        "commodity_future": "Commodity futures",
    }
    for mode, row in scan_status().items():
        total = int(row.get("total") or 0)
        if row.get("running") and total:
            if ":" in mode:
                book, kind = mode.split(":", 1)
                label = f"{books.get(book, book)} {labels.get(kind, kind).lower()}"
            else:
                label = labels.get(mode, mode)
            lines.append(f"{label}: {int(row.get('done') or 0)} of {total} names.")
    return lines


def _launch(record: dict) -> None:
    global _RUNNING, _RECORD, _WORKING, _FOCUS
    user = str(record.get("platform_user_id") or "")
    if user:
        from kite_app.equity_queue import enqueue_equity_pass

        if enqueue_equity_pass(user):
            with _LOCK:
                _RECORD = record
                _WORKING = True
                _FOCUS = "Queued equities, stock futures, stock options, and commodity futures. Batches keep running if this page closes."
            return
    with _LOCK:
        _RECORD = record
        if _RUNNING:
            return
        _RUNNING = True
        _WORKING = True
        if not _FOCUS:
            _FOCUS = "Reading equities, stock futures, stock options, and commodity futures."
    threading.Thread(target=_loop, daemon=True).start()


def handle_message(body: dict) -> None:
    """Run one queued batch. The caller deletes the message only after this returns."""
    kind = str(body.get("kind") or "")
    if kind == "equity_pass":
        _handle_pass(body)
        return
    if kind == "screen":
        _handle_screen(body)
        return
    if kind == "review":
        _handle_review(body)


def _handle_pass(body: dict) -> None:
    user = str(body.get("platform_user_id") or "")
    wave = int(body.get("wave") or 0) + 1
    record = _session_for(user)
    if record is None:
        _set_working(False, "Log in to Zerodha to read equities, stock futures, stock options, and commodity futures.")
        return
    if wave > _PASS_LIMIT:
        _set_working(False, "The equity read is still going. Open Final list again to continue.")
        return
    from kite_app.scan_jobs import ensure_listed_equity_scan, equity_work_pending

    ensure_listed_equity_scan(record)
    symbols = _next_symbols()
    from kite_app.equity_queue import enqueue_equity_pass, enqueue_screen_batches

    if symbols:
        sent = enqueue_screen_batches(user, symbols)
        if sent < 1:
            raise RuntimeError("screen batches were not queued")
        _mark_seen(symbols)
        enqueue_equity_pass(user, delay_seconds=15, wave=wave)
        _set_working(True, f"Queued {sent} names for batch screening.")
        return
    if equity_work_pending():
        enqueue_equity_pass(user, delay_seconds=20, wave=wave)
        _set_working(True, "Waiting for the next price batch.")
        return
    _set_working(False, "The equity read is finished.")


def _handle_screen(body: dict) -> None:
    symbols = [str(symbol).upper() for symbol in body.get("symbols") or [] if str(symbol).strip()]
    if not symbols:
        return
    wanted = set(symbols)
    stocks = [row for row in _load_stocks() if str(row.get("symbol") or "").upper() in wanted]
    _set_focus(f"Screening a batch of {len(symbols)} names.")
    from kite_app.algo_layers import select_setups

    book = select_setups(stocks, review=False)
    user = str(body.get("platform_user_id") or "")
    review_symbols = []
    for item in [*book["setups"], *book["sell_calls"]]:
        symbol = str(item.get("symbol") or "")
        if symbol and _review_key(item) not in _REVIEWS and symbol not in _REVIEW_QUEUED:
            review_symbols.append(symbol)
    if review_symbols and user:
        from kite_app.equity_queue import enqueue_reviews

        if enqueue_reviews(user, review_symbols) < 1:
            raise RuntimeError("review batches were not queued")
        _REVIEW_QUEUED.update(review_symbols)
    with _LOCK:
        _BOOK["scanned"] = int(_BOOK["scanned"]) + len(symbols)
        _BOOK["accepted"] = int(_BOOK["accepted"]) + int(book["accepted"])
    if review_symbols:
        _set_focus(f"Queued {', '.join(review_symbols[:5])} for filings, news, and lawsuits.")


def _handle_review(body: dict) -> None:
    symbol = str(body.get("symbol") or "").upper()
    if not symbol:
        return
    stocks = [row for row in _load_stocks() if str(row.get("symbol") or "").upper() == symbol]
    if not stocks:
        _set_focus(f"{symbol} is waiting for saved prices.")
        return
    from kite_app.algo_layers import select_setups

    book = select_setups(stocks, review=False)
    rows = [*book["setups"], *book["sell_calls"]]
    if not rows:
        return
    _set_focus(f"Reading filings, news, and lawsuits for {symbol}.")
    _review_rows(rows)
    _remember(rows)


def _next_symbols() -> list[str]:
    found = []
    for row in _load_stocks():
        symbol = str(row.get("symbol") or "").upper()
        if not symbol or symbol in _SEEN:
            continue
        found.append(symbol)
        if len(found) >= _SLICE:
            break
    return found


def _mark_seen(symbols: list[str]) -> None:
    _SEEN.update(str(symbol).upper() for symbol in symbols if symbol)


def _remember(rows: list[dict]) -> None:
    with _LOCK:
        buys = {str(item.get("symbol") or ""): dict(item) for item in _BOOK["setups"]}
        sells = {str(item.get("symbol") or ""): dict(item) for item in _BOOK["sell_calls"]}
        for item in rows:
            symbol = str(item.get("symbol") or "")
            if not symbol:
                continue
            if item.get("ai_decision") == "sell":
                sells[symbol] = dict(item)
            elif item.get("ai_decision") == "buy":
                buys[symbol] = dict(item)
        _BOOK["setups"] = list(buys.values())[:5]
        _BOOK["sell_calls"] = list(sells.values())[:5]


def _session_for(user_id: str) -> Optional[dict]:
    import os

    from kite_app.identity_store import current_desk_session

    try:
        user = uuid.UUID(str(user_id))
    except ValueError:
        return None
    record = current_desk_session(user)
    if not record:
        return None
    record["api_key"] = os.environ.get("KITE_API_KEY", "").strip()
    if not record.get("api_key") or not record.get("access_token"):
        return None
    return record


async def serve_queue(stop) -> None:
    """Long-poll SQS without blocking the desk request."""
    import asyncio

    from kite_app.equity_queue import delete_batch, extend_visibility, receive_batch

    while not stop.is_set():
        try:
            messages = await asyncio.to_thread(receive_batch)
        except Exception:
            logger.info("equity queue was not read")
            try:
                await asyncio.wait_for(stop.wait(), timeout=15)
            except asyncio.TimeoutError:
                continue
            return
        if not messages:
            try:
                await asyncio.wait_for(stop.wait(), timeout=15)
            except asyncio.TimeoutError:
                continue
            return
        for message in messages:
            receipt = str(message.get("receipt") or "")
            body = message.get("body") if isinstance(message.get("body"), dict) else {}
            try:
                if body.get("kind") == "review":
                    await asyncio.to_thread(extend_visibility, receipt)
                await asyncio.to_thread(handle_message, body)
                await asyncio.to_thread(delete_batch, [receipt])
            except Exception:
                logger.info("equity message was not finished")


def _loop() -> None:
    global _RUNNING
    started = time.monotonic()
    try:
        while time.monotonic() - started < 45 * 60:
            record = _current_record()
            try:
                from kite_app.scan_jobs import ensure_listed_equity_scan, equity_work_pending

                if record:
                    ensure_listed_equity_scan(record)
                pending = equity_work_pending()
            except Exception:
                logger.info("final list scan was not started")
                pending = True
            try:
                refresh_book()
            except Exception:
                logger.info("final list screen paused")
                _set_focus("The screen paused. It will try again.")
            if not pending:
                _set_working(False, "The equity read is finished.")
                return
            time.sleep(5)
        _set_working(False, "The equity read is still going. Open Final list again to continue.")
    finally:
        with _LOCK:
            _RUNNING = False


def _current_record() -> Optional[dict]:
    with _LOCK:
        return _RECORD


def _set_working(working: bool, focus: str) -> None:
    global _WORKING, _FOCUS
    with _LOCK:
        _WORKING = working
        _FOCUS = focus


def _set_focus(focus: str) -> None:
    global _FOCUS
    with _LOCK:
        _FOCUS = focus


def _review_key(item: dict) -> str:
    return f"{item.get('symbol')}|{item.get('entry')}|{item.get('last_close')}"
