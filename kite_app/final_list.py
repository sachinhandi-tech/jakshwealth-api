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
_FINISHED = False
_FOCUS = ""
_BOOK = {"scanned": 0, "accepted": 0, "setups": [], "sell_calls": [], "vetoes": []}
_REVIEWS: dict[str, dict] = {}
_LAST_SCREEN = 0.0
_LAST_COUNT = -1
_RECORD: Optional[dict] = None
_SEEN: set[str] = set()
_SCREENED: set[str] = set()
_REVIEW_QUEUED: set[str] = set()
_PASSED: dict[str, dict] = {}
_STAMP = ("ai_decision", "ai_checks", "ai_reason", "gtt_tradable", "reason")
_PASS_LIMIT = 80
_SLICE = 250


_STOP_NOTE = "Scan stopped. Start from zero when you want a new read from the first name."


def _login_note() -> str:
    from kite_app.scanner_data import cap_segment_note

    return f"Log in to Zerodha to read {cap_segment_note()} equities."


def _read_note() -> str:
    from kite_app.scanner_data import cap_segment_note

    return f"Reading {cap_segment_note()} equities."


def begin_final_list(record: Optional[dict], launch: bool = True) -> dict:
    """Start the equity read if needed and return the lines the desk can show now."""
    from kite_app.desk_progress import scan_paused

    if not record or not record.get("api_key") or not record.get("access_token"):
        _set_working(False, _login_note())
        return public_snapshot()
    if scan_paused():
        _set_working(False, _FOCUS or _STOP_NOTE)
        return public_snapshot()
    if launch:
        _launch(record)
    else:
        _set_working(True, _FOCUS or _read_note())
    return public_snapshot()


def stop_scan() -> dict:
    """Stop the read. The next pass starts only when you ask to start from zero."""
    from kite_app.desk_progress import pause_scan

    pause_scan()
    _set_working(False, _STOP_NOTE)
    return public_snapshot()


def start_from_zero(record: Optional[dict], caps: Optional[list[str]] = None) -> dict:
    """Drop this read's progress and start again at the first NSE share."""
    global _FINISHED, _LAST_COUNT, _RUNNING, _SEEN, _SCREENED, _REVIEW_QUEUED, _REVIEWS, _PASSED
    from kite_app.desk_progress import bump_generation, clear_activity, resume_scan
    from kite_app.scanner_data import selected_cap_segments, set_cap_segments

    # Restart with an explicit list pins the universe. continue_scan passes None and
    # must keep whatever large/mid/small selection is already active.
    if caps is None:
        chosen = selected_cap_segments()
    else:
        chosen = set_cap_segments(caps)
    if not record or not record.get("api_key") or not record.get("access_token"):
        _set_working(False, _login_note())
        return public_snapshot()
    bump_generation()
    clear_activity()
    with _LOCK:
        _SEEN = set()
        _SCREENED = set()
        _REVIEW_QUEUED = set()
        _REVIEWS = {}
        _PASSED = {}
        _LAST_COUNT = -1
        _FINISHED = False
        _BOOK["scanned"] = 0
        _BOOK["accepted"] = 0
        _BOOK["setups"] = []
        _BOOK["sell_calls"] = []
        _BOOK["vetoes"] = []
        _RUNNING = False
    # Clear coverage before any poll can relaunch against the previous mid/small list.
    try:
        from kite_app.scan_jobs import forget_saved_scans

        forget_saved_scans()
    except Exception:
        logger.info("saved scan coverage was not cleared")
    resume_scan()
    labels = ", ".join(chosen)
    _set_working(True, f"Starting again from the first NSE share ({labels}).")
    snapshot = public_snapshot()
    threading.Thread(target=_begin_again, args=(record,), daemon=True).start()
    return snapshot


def _begin_again(record: dict) -> None:
    """Start the read after coverage was cleared on the request thread."""
    try:
        _launch(record)
    except Exception:
        logger.info("scan was not started")


def _message_is_current(body: dict) -> bool:
    """Drop older-generation work. Same-generation messages carry the desk caps.

    SQS workers may not have seen the HTTP Start-from-zero yet. When the
    generation matches, adopt the caps stamped on the message so a large-only
    restart cannot keep screening mid/small on a stale worker.
    """
    from kite_app.desk_progress import current_generation
    from kite_app.scanner_data import normalize_cap_segments, selected_cap_segments, set_cap_segments

    raw = body.get("generation")
    if raw is None:
        # Legacy messages without a generation stamp are ignored after a restart
        # so they cannot rewrite the desk's large/mid/small selection.
        return current_generation() == 0
    try:
        if int(raw) != current_generation():
            return False
    except (TypeError, ValueError):
        return False
    message_caps = normalize_cap_segments(
        body.get("caps") if isinstance(body.get("caps"), list) else None,
        require=True,
    )
    if not message_caps:
        return False
    if set(message_caps) != set(selected_cap_segments()):
        set_cap_segments(message_caps)
    return True


def continue_scan(record: Optional[dict]) -> dict:
    """Older clients use this path. It starts again from the first name."""
    return start_from_zero(record)


def public_snapshot() -> dict:
    from kite_app.scanner_data import selected_cap_segments

    with _LOCK:
        book = {
            "scanned": _BOOK["scanned"],
            "accepted": _BOOK["accepted"],
            "setups": [dict(item) for item in _BOOK["setups"]],
            "sell_calls": [dict(item) for item in _BOOK["sell_calls"]],
            "vetoes": [dict(item) for item in _BOOK.get("vetoes") or []],
            "passed": [
                dict(item)
                for item in sorted(_PASSED.values(), key=lambda row: str(row.get("symbol") or ""))
            ],
            "working": _WORKING and not _FINISHED,
            "paused": _paused(),
            "finished": _FINISHED,
            "caps": selected_cap_segments(),
        }
        focus = _FOCUS
    progress = _scan_progress()
    if book["finished"]:
        # One clear outcome line. Never mix "finished" with "% remaining" chatter.
        note = focus or _finished_note()
        book["activity"] = [{"text": note, "state": "done"}]
        book["progress"] = None
        book["universe_note"] = note
        return book
    lines = _progress_lines()
    if focus and focus not in lines and "% remaining." not in focus and not _scan_chatter(focus):
        lines.append(focus)
    if progress:
        kept = [line for line in lines if not _scan_chatter(line) and "% remaining." not in line]
        kept.append(_count_line())
        lines = kept
    if not lines:
        lines = [_read_note()]
    activity = []
    for index, text in enumerate(lines[-5:]):
        active = book["working"] and index == len(lines[-5:]) - 1
        activity.append({"text": text, "state": "active" if active else "done"})
    book["activity"] = activity
    book["progress"] = progress
    book["universe_note"] = activity[-1]["text"] if activity else ""
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
    from kite_app.scanner_data import listed_cap_symbols, selected_cap_segments
    from kite_app.signals_cache import history_by_ticker

    signals = latest_crossover_signals()
    remembered = history_by_ticker([signal["symbol"] for signal in signals]) if signals else []
    stocks = combine_books([], signals, remembered)
    try:
        allowed = {symbol.upper() for symbol in listed_cap_symbols(selected_cap_segments())}
    except Exception:
        logger.info("selected cap lists were not loaded; screening waits for the chosen universe")
        return []
    return [row for row in stocks if str(row.get("symbol") or "").upper() in allowed]


def _screen_total(saved_count: int = 0) -> int:
    """Denominator for the screen meter.

    While prices are still loading, aim at the full selected cap list.
    Once the equity pass is idle, only names that actually became screenable
    count — otherwise the desk sits forever at e.g. 217/247 with 12% left.
    """
    screened = len(_SCREENED)
    baseline = max(int(saved_count), screened)
    try:
        from kite_app.scan_jobs import equity_work_pending

        pending = equity_work_pending()
    except Exception:
        pending = False
    if not pending:
        return max(baseline, 1) if baseline else 0
    try:
        from kite_app.scanner_data import listed_cap_symbols, selected_cap_segments

        return max(baseline, len(listed_cap_symbols(selected_cap_segments())))
    except Exception:
        return baseline


def _equity_progress_label() -> str:
    try:
        from kite_app.scanner_data import cap_segment_note

        return cap_segment_note()
    except Exception:
        return "NSE equities"


def _progress_lines() -> list[str]:
    from kite_app.desk_progress import activity_status, scan_status

    lines = [
        line for line in activity_status()
        if "read is finished" not in str(line or "").lower()
    ]
    if _FINISHED:
        return activity_status()
    books = {
        "equity": _equity_progress_label(),
        "commodity_future": "Commodity futures",
    }
    for mode, row in scan_status().items():
        if mode == "screen":
            continue
        total = int(row.get("total") or 0)
        if row.get("running") and total:
            book = mode.split(":", 1)[0] if ":" in mode else "equity"
            label = books.get(book, "Names")
            done = int(row.get("done") or 0)
            remaining = _remaining_percent(done, total)
            lines.append(f"{label}: {done} of {total} names. {remaining}% remaining.")
    return lines


def _count_line() -> str:
    progress = _scan_progress()
    if not progress:
        return "Fetching the NSE share list from Zerodha."
    action = progress.get("action") or "scanned"
    return (
        f"{progress['done']:,} of {progress['total']:,} {progress['label']} {action}. "
        f"{progress['remaining_percent']}% remaining."
    )


def _remaining_percent(done: int, total: int) -> int:
    if total <= 0 or done <= 0:
        return 100 if total > 0 else 0
    if done >= total:
        return 0
    return min(round((total - done) * 100 / total), 99)


def _scan_chatter(text: str) -> bool:
    line = str(text or "").strip()
    return (
        line.startswith("Asking Zerodha")
        or line.startswith("Starting NSE")
        or line.startswith("Starting Commodity")
        or line.startswith("Saved prices already cover")
        or line.startswith("NSE equities:")
        or line.startswith("Commodity futures:")
    )


def _scan_progress() -> Optional[dict]:
    from kite_app.desk_progress import scan_status

    books = {
        "equity": _equity_progress_label(),
        "commodity_future": "Commodity futures",
    }
    running_book = None
    running_screen = None
    finished_screen = None
    chosen = None
    for mode, row in scan_status().items():
        total = int(row.get("total") or 0)
        if total <= 0:
            continue
        book = mode.split(":", 1)[0] if ":" in mode else "equity"
        done = int(row.get("done") or 0)
        payload = {
            "done": done,
            "total": total,
            "label": str(row.get("label") or "") or books.get(book, "Names"),
            "action": str(row.get("action") or "scanned"),
            "remaining_percent": _remaining_percent(done, total),
        }
        chosen = payload
        if mode == "screen":
            finished_screen = payload
        if not row.get("running"):
            continue
        if mode == "screen":
            running_screen = payload
        elif running_book is None:
            running_book = payload
    if _FINISHED:
        # After the read ends, keep the screen total. Do not revive a leftover price-scan meter.
        return finished_screen
    return running_book or running_screen or finished_screen or chosen


def _launch(record: dict) -> None:
    global _RUNNING, _RECORD, _WORKING, _FOCUS
    if _read_is_complete():
        return
    user = str(record.get("platform_user_id") or "")
    if user:
        try:
            from kite_app.equity_queue import enqueue_equity_pass

            queued = enqueue_equity_pass(user)
        except Exception:
            queued = False
        if queued:
            with _LOCK:
                _RECORD = record
                already = _WORKING
                _WORKING = True
                if not _FOCUS:
                    _FOCUS = _read_note()
            if not already:
                _note_activity_line(_read_note())
            return
    with _LOCK:
        _RECORD = record
        if _RUNNING:
            return
        _RUNNING = True
        _WORKING = True
        if not _FOCUS:
            _FOCUS = _read_note()
        focus = _FOCUS
    _note_activity_line(focus)
    threading.Thread(target=_loop, daemon=True).start()


def handle_message(body: dict) -> None:
    """Run one queued batch. The caller deletes the message only after this returns."""
    if _paused():
        return
    if not _message_is_current(body):
        # Stale large/mid/small work must not mutate the current desk selection.
        return
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
    if _FINISHED:
        return
    user = str(body.get("platform_user_id") or "")
    wave = int(body.get("wave") or 0) + 1
    record = _session_for(user)
    if record is None:
        _set_working(False, _login_note())
        return
    if wave > _PASS_LIMIT:
        _set_working(False, "The equity read is still going. Open Final list again to continue.")
        return
    from kite_app.scan_jobs import ensure_listed_equity_scan, equity_work_pending

    ensure_listed_equity_scan(record)
    saved = _saved_symbols()
    symbols = _next_symbols(saved)
    from kite_app.equity_queue import enqueue_equity_pass, enqueue_screen_batches

    if symbols:
        sent = enqueue_screen_batches(user, symbols)
        if sent < 1:
            raise RuntimeError("screen batches were not queued")
        _mark_seen(symbols)
        enqueue_equity_pass(user, delay_seconds=15, wave=wave)
        _note_screen_progress(len(_SCREENED), _screen_total(len(saved)))
        _set_working(True, _count_line())
        return
    if equity_work_pending() or _screens_pending():
        # Prices still loading, or screen batches are still in flight after being queued.
        enqueue_equity_pass(user, delay_seconds=20, wave=wave)
        total = _screen_total(len(saved))
        if total:
            _note_screen_progress(len(_SCREENED), total)
        waiting = (
            "Waiting for the selected large/mid/small cap prices."
            if equity_work_pending() and not total
            else _count_line()
        )
        _set_working(True, waiting)
        return
    if _reviews_pending():
        _set_working(True, "Reading filings, news, and lawsuits for names that passed every screen.")
        return
    _mark_finished(_finished_note())


def _handle_screen(body: dict) -> None:
    if _FINISHED:
        return
    from kite_app.scanner_data import filter_symbols_to_caps

    raw_symbols = [str(symbol).upper() for symbol in body.get("symbols") or [] if str(symbol).strip()]
    symbols = filter_symbols_to_caps(raw_symbols)
    if not symbols:
        # Cap filter dropped the batch; still clear the queued SEEN entries so finish can run.
        _mark_screened(raw_symbols)
        _finish_if_idle()
        return
    wanted = set(symbols)
    stocks = [row for row in _load_stocks() if str(row.get("symbol") or "").upper() in wanted]
    from kite_app.algo_layers import select_setups

    book = select_setups(stocks, review=False)
    passed = book.get("passed")
    if not isinstance(passed, list):
        passed = [*book["setups"], *book["sell_calls"]]
    _note_passed(passed)
    user = str(body.get("platform_user_id") or "")
    review_symbols = []
    for item in passed:
        symbol = str(item.get("symbol") or "")
        if symbol and _review_key(item) not in _REVIEWS and symbol not in _REVIEW_QUEUED:
            review_symbols.append(symbol)
    review_symbols = filter_symbols_to_caps(review_symbols)
    if review_symbols and user:
        from kite_app.equity_queue import enqueue_reviews

        if enqueue_reviews(user, review_symbols) < 1:
            raise RuntimeError("review batches were not queued")
        _REVIEW_QUEUED.update(review_symbols)
    done = _mark_screened(symbols)
    with _LOCK:
        _BOOK["scanned"] = int(_BOOK["scanned"]) + len(symbols)
        _BOOK["accepted"] = int(_BOOK["accepted"]) + int(book["accepted"])
    _note_screen_progress(done, _screen_total(max(done, len(_saved_symbols()))))
    _set_working(True, _count_line())
    if review_symbols:
        _set_focus(f"Queued {', '.join(review_symbols[:5])} for filings, news, and lawsuits.")
    _finish_if_idle()


def _handle_review(body: dict) -> None:
    if _FINISHED:
        return
    from kite_app.scanner_data import filter_symbols_to_caps

    symbol = str(body.get("symbol") or "").upper()
    if not symbol or filter_symbols_to_caps([symbol]) != [symbol]:
        _REVIEW_QUEUED.discard(symbol)
        _finish_if_idle()
        return
    stocks = [row for row in _load_stocks() if str(row.get("symbol") or "").upper() == symbol]
    if not stocks:
        _REVIEW_QUEUED.discard(symbol)
        _set_focus(f"{symbol} is waiting for saved prices.")
        _finish_if_idle()
        return
    from kite_app.algo_layers import select_setups

    book = select_setups(stocks, review=False)
    rows = [*book["setups"], *book["sell_calls"]]
    if not rows:
        _REVIEW_QUEUED.discard(symbol)
        _finish_if_idle()
        return
    _set_focus(f"Reading filings, news, and lawsuits for {symbol}.")
    _review_rows(rows)
    _remember_setups(rows)
    _mark_passed_status(rows)
    _REVIEW_QUEUED.discard(symbol)
    buys = [str(item.get("symbol") or "") for item in rows if item.get("ai_decision") == "buy"]
    if buys:
        _set_focus(f"{', '.join(buys)} is approved and ready for a Zerodha buy GTT.")
    else:
        veto = next((item for item in rows if item.get("ai_reason")), None)
        if veto:
            _set_focus(
                f"{veto.get('symbol')} passed every screen, but the model did not approve a buy. "
                f"{veto.get('ai_reason')}"
            )
    _finish_if_idle()


def _saved_symbols() -> list[str]:
    found = []
    seen: set[str] = set()
    for row in _load_stocks():
        symbol = str(row.get("symbol") or "").upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        found.append(symbol)
    return found


def _next_symbols(saved: Optional[list[str]] = None) -> list[str]:
    rows = _saved_symbols() if saved is None else saved
    return [symbol for symbol in rows if symbol not in _SEEN][:_SLICE]


def _note_passed(rows: list[dict]) -> None:
    """Remember every name that cleared the screens, before the model reads it."""
    global _PASSED
    with _LOCK:
        for item in rows:
            symbol = str(item.get("symbol") or "").upper()
            if not symbol or symbol in _PASSED:
                continue
            _PASSED[symbol] = {
                "symbol": symbol,
                "company_name": str(item.get("company_name") or ""),
                "last_close": item.get("last_close"),
                "status": "waiting",
            }


def _mark_passed_status(rows: list[dict]) -> None:
    with _LOCK:
        for item in rows:
            symbol = str(item.get("symbol") or "").upper()
            row = _PASSED.get(symbol)
            if not row:
                continue
            decision = str(item.get("ai_decision") or "").strip()
            if decision:
                row["status"] = decision


def _mark_screened(symbols: list[str]) -> int:
    global _SCREENED
    with _LOCK:
        _SCREENED.update(str(symbol).upper() for symbol in symbols if symbol)
        return len(_SCREENED)


def _note_screen_progress(done: int, total: Optional[int] = None) -> None:
    if _FINISHED:
        return
    from kite_app.desk_progress import note_scan, scan_status

    if total is None:
        total = int((scan_status().get("screen") or {}).get("total") or 0)
    total = max(int(total), int(done))
    if total <= 0:
        return
    note_scan(
        "screen",
        done,
        total,
        0,
        done < total,
        label="names",
        action="screened",
    )


def _mark_seen(symbols: list[str]) -> None:
    _SEEN.update(str(symbol).upper() for symbol in symbols if symbol)


def _screens_pending() -> bool:
    """True while queued screen batches have not all reported back."""
    with _LOCK:
        return bool(_SEEN - _SCREENED)


def _remember_setups(rows: list[dict]) -> None:
    """Merge reviewed buy/sell/veto rows into the live book the desk shows."""
    with _LOCK:
        buys = {str(item.get("symbol") or ""): dict(item) for item in _BOOK["setups"]}
        sells = {str(item.get("symbol") or ""): dict(item) for item in _BOOK["sell_calls"]}
        vetoes = {str(item.get("symbol") or ""): dict(item) for item in _BOOK.get("vetoes") or []}
        for item in rows:
            symbol = str(item.get("symbol") or "")
            if not symbol:
                continue
            decision = str(item.get("ai_decision") or "")
            if decision == "sell":
                sells[symbol] = dict(item)
                buys.pop(symbol, None)
                vetoes.pop(symbol, None)
            elif decision == "buy":
                buys[symbol] = dict(item)
                vetoes.pop(symbol, None)
            elif decision in {"stand_aside", "unavailable"}:
                vetoes[symbol] = dict(item)
                buys.pop(symbol, None)
        _BOOK["setups"] = list(buys.values())[:5]
        _BOOK["sell_calls"] = list(sells.values())[:5]
        _BOOK["vetoes"] = list(vetoes.values())[:5]


def _reviews_pending() -> bool:
    with _LOCK:
        reviewed = {
            str(key).split("|", 1)[0].upper()
            for key in _REVIEWS
            if str(key).strip()
        }
        return any(symbol not in reviewed for symbol in _REVIEW_QUEUED)


def _read_is_complete() -> bool:
    with _LOCK:
        if _FINISHED:
            return True
    try:
        from kite_app.scan_jobs import equity_work_pending

        pending = equity_work_pending()
    except Exception:
        pending = True
    return (
        (not pending)
        and (not _next_symbols())
        and (not _screens_pending())
        and (not _reviews_pending())
        and (not _WORKING)
    )


def _finished_note() -> str:
    with _LOCK:
        screened = len(_SCREENED)
        accepted = int(_BOOK["accepted"] or 0)
        buys = len(_BOOK["setups"])
        vetoes = [dict(item) for item in _BOOK.get("vetoes") or []]
    from kite_app.scanner_data import cap_segment_note

    universe = cap_segment_note()
    if buys:
        return f"The {universe} read is finished. {buys} approved buy{'s' if buys != 1 else ''} ready."
    if accepted:
        veto = next((item for item in vetoes if item.get("ai_reason")), None)
        if veto:
            symbol = str(veto.get("symbol") or "A name")
            reason = str(veto.get("ai_reason") or "").strip()
            return (
                f"The {universe} read is finished. {symbol} passed every screen, "
                f"but the model did not approve a buy. {reason}"
            )
        return (
            f"The {universe} read is finished. {accepted} name{'s' if accepted != 1 else ''} passed every screen, "
            "but the model did not approve a buy."
        )
    if screened:
        return (
            f"The {universe} read is finished. None of the {screened} screened names passed "
            "price/volume, risk/momentum, and the model screens together."
        )
    return f"The {universe} read is finished. No names were ready to screen yet."


def _mark_finished(focus: str) -> None:
    global _FINISHED
    from kite_app.desk_progress import clear_activity, note_scan, scan_status

    with _LOCK:
        if _FINISHED:
            return
        _FINISHED = True
        screened = len(_SCREENED)
    # Drop leftover "% remaining" lines so the desk only shows the outcome.
    clear_activity()
    # Snap the screen meter to 100% so a finished read never sits at "12% remaining".
    if screened > 0:
        note_scan("screen", screened, screened, 0, False, label="names", action="screened")
    # Stop leftover price-scan meters so the desk does not show "5 of 495" after a finished large-cap read.
    for mode, row in scan_status().items():
        if mode == "screen" or not row.get("running"):
            continue
        note_scan(
            mode,
            int(row.get("done") or 0),
            int(row.get("total") or 0),
            int(row.get("signals") or 0),
            False,
            label=str(row.get("label") or ""),
            action=str(row.get("action") or ""),
        )
    _set_working(False, focus)


def _finish_if_idle() -> None:
    if _FINISHED:
        return
    try:
        from kite_app.scan_jobs import equity_work_pending

        pending = equity_work_pending()
    except Exception:
        pending = True
    if pending or _next_symbols() or _screens_pending() or _reviews_pending():
        return
    _mark_finished(_finished_note())


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
        if _paused():
            try:
                await asyncio.wait_for(stop.wait(), timeout=15)
            except asyncio.TimeoutError:
                continue
            return
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
    from kite_app.desk_progress import current_generation

    started = time.monotonic()
    generation = current_generation()
    try:
        while time.monotonic() - started < 45 * 60:
            if _paused():
                _set_working(False, _STOP_NOTE)
                return
            if current_generation() != generation:
                return
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
            if not pending and not _next_symbols() and not _screens_pending():
                if _reviews_pending():
                    _set_working(True, "Reading filings, news, and lawsuits for names that passed every screen.")
                else:
                    _finish_if_idle()
                    if _FINISHED:
                        return
            time.sleep(5)
        _set_working(False, "The equity read is still going. Open Final list again to continue.")
    finally:
        with _LOCK:
            _RUNNING = False


def _current_record() -> Optional[dict]:
    with _LOCK:
        return _RECORD


def _paused() -> bool:
    from kite_app.desk_progress import scan_paused

    return scan_paused()


def _set_working(working: bool, focus: str) -> None:
    global _WORKING, _FOCUS
    with _LOCK:
        if _FINISHED and working:
            # A finished read must not flip back to "still working" from a late batch.
            return
        _WORKING = working and not _FINISHED
        _FOCUS = focus
    _note_activity_line(focus)


def _set_focus(focus: str) -> None:
    global _FOCUS
    with _LOCK:
        _FOCUS = focus
    if _FINISHED and "% remaining." in focus:
        return
    _note_activity_line(focus)


def _note_activity_line(focus: str) -> None:
    from kite_app.desk_progress import note_activity

    note_activity(focus)


def _review_key(item: dict) -> str:
    return f"{item.get('symbol')}|{item.get('entry')}|{item.get('last_close')}"
