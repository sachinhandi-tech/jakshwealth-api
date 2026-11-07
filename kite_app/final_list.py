"""Final list. The HTTP call returns immediately. Screening and the model run behind it."""

from __future__ import annotations

import copy
import logging
import threading
import time
import uuid
from typing import Optional

logger = logging.getLogger("kite_app.final_list")

_LOCK = threading.RLock()
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
_MODEL_RETRY_LIMIT = 6
_MODES = {"screens", "wealth30"}
_MODE = "screens"
# Each read keeps its own names, caps, and generation. Switching tabs must not clear the other one.
_SAVED: dict[str, dict] = {}
_GEN: dict[str, Optional[int]] = {"screens": None, "wealth30": None}
_CAPS: dict[str, list] = {"screens": [], "wealth30": []}
_PAUSED_MODES: set[str] = set()
_CAPS_LOCAL = threading.local()
_LAST_SNAPSHOT: dict = {}
_TOUCHING = False


_STOP_NOTE = "Scan stopped. Start from zero when you want a new read from the first name."


def _login_note() -> str:
    from kite_app.scanner_data import cap_segment_note

    return f"Log in to Zerodha to read {cap_segment_note()} equities."


def _read_note() -> str:
    from kite_app.scanner_data import cap_segment_note

    return f"Reading {cap_segment_note()} equities."


def begin_final_list(record: Optional[dict], launch: bool = True) -> dict:
    """Return both reads. A poll must not start or stop either of them."""
    from kite_app.desk_progress import scan_paused

    if not record or not record.get("api_key") or not record.get("access_token"):
        _set_working(False, _login_note())
        return public_snapshot()
    mode = current_scan_mode()
    if mode in _PAUSED_MODES:
        return public_snapshot()
    if scan_paused() and not _other_working(mode):
        _set_working(False, _FOCUS or _STOP_NOTE)
        return public_snapshot()
    if launch:
        _launch(record)
    return public_snapshot()


def stop_scan(mode: str = "screens") -> dict:
    """Stop one read. The other read keeps going."""
    mode = mode if mode in _MODES else "screens"
    with _LOCK:
        _switch_to_locked(mode)
        _PAUSED_MODES.add(mode)
        other_live = _other_working(mode)
    if not other_live:
        from kite_app.desk_progress import pause_scan

        pause_scan()
    _set_working(False, _STOP_NOTE)
    return public_snapshot()


def current_scan_mode() -> str:
    """screens keeps the price filters. wealth30 sends every ticked cap name to the 30 points."""
    return _MODE if _MODE in _MODES else "screens"


def _other_mode(mode: str) -> str:
    return "wealth30" if mode == "screens" else "screens"


def _other_working(mode: str) -> bool:
    """True when the read that is not `mode` still has work in flight."""
    other = _other_mode(mode)
    if other == _MODE:
        return bool(_WORKING) and not _FINISHED
    snap = _SAVED.get(other)
    if not snap:
        return False
    return bool(snap.get("working")) and not snap.get("finished")


def _capture_locked() -> dict:
    progress = None
    try:
        progress = _scan_progress()
    except Exception:
        progress = None
    return {
        "running": _RUNNING,
        "working": _WORKING,
        "finished": _FINISHED,
        "focus": _FOCUS,
        "book": {
            "scanned": int(_BOOK.get("scanned") or 0),
            "accepted": int(_BOOK.get("accepted") or 0),
            "setups": copy.deepcopy(_BOOK.get("setups") or []),
            "sell_calls": copy.deepcopy(_BOOK.get("sell_calls") or []),
            "vetoes": copy.deepcopy(_BOOK.get("vetoes") or []),
        },
        "reviews": copy.deepcopy(_REVIEWS),
        "last_count": _LAST_COUNT,
        "seen": set(_SEEN),
        "screened": set(_SCREENED),
        "review_queued": set(_REVIEW_QUEUED),
        "passed": copy.deepcopy(_PASSED),
        "progress": progress,
    }


def _restore_locked(snap: dict) -> None:
    global _RUNNING, _WORKING, _FINISHED, _FOCUS, _BOOK, _REVIEWS, _LAST_COUNT
    global _SEEN, _SCREENED, _REVIEW_QUEUED, _PASSED
    _RUNNING = bool(snap.get("running"))
    _WORKING = bool(snap.get("working"))
    _FINISHED = bool(snap.get("finished"))
    _FOCUS = str(snap.get("focus") or "")
    _BOOK = snap.get("book") or {"scanned": 0, "accepted": 0, "setups": [], "sell_calls": [], "vetoes": []}
    _REVIEWS = snap.get("reviews") or {}
    _LAST_COUNT = snap.get("last_count", -1)
    _SEEN = snap.get("seen") or set()
    _SCREENED = snap.get("screened") or set()
    _REVIEW_QUEUED = snap.get("review_queued") or set()
    _PASSED = snap.get("passed") or {}


def _blank_locked() -> None:
    global _RUNNING, _WORKING, _FINISHED, _FOCUS, _BOOK, _REVIEWS, _LAST_COUNT
    global _SEEN, _SCREENED, _REVIEW_QUEUED, _PASSED
    _RUNNING = False
    _WORKING = False
    _FINISHED = False
    _FOCUS = ""
    _BOOK = {"scanned": 0, "accepted": 0, "setups": [], "sell_calls": [], "vetoes": []}
    _REVIEWS = {}
    _LAST_COUNT = -1
    _SEEN = set()
    _SCREENED = set()
    _REVIEW_QUEUED = set()
    _PASSED = {}


def _switch_to_locked(mode: str) -> None:
    """Caller holds _LOCK. Park the live read and load the one this message belongs to."""
    global _MODE
    mode = mode if mode in _MODES else "screens"
    if mode == _MODE:
        return
    _SAVED[_MODE] = _capture_locked()
    snap = _SAVED.get(mode)
    if snap:
        _restore_locked(snap)
    else:
        _blank_locked()
    _MODE = mode


def _active_caps() -> list:
    local = getattr(_CAPS_LOCAL, "caps", None)
    if local:
        return list(local)
    from kite_app.scanner_data import selected_cap_segments

    return selected_cap_segments()


def enqueue_stamp() -> tuple:
    """Caps, mode, and generation for the read this thread is queueing."""
    from kite_app.desk_progress import current_generation
    from kite_app.scanner_data import selected_cap_segments

    local_mode = getattr(_CAPS_LOCAL, "mode", None)
    mode = local_mode if local_mode in _MODES else current_scan_mode()
    caps = list(getattr(_CAPS_LOCAL, "caps", None) or [])
    if not caps:
        caps = list(selected_cap_segments())
    generation = getattr(_CAPS_LOCAL, "generation", None)
    if generation is None:
        pinned = _GEN.get(mode)
        if local_mode in _MODES and pinned is not None:
            generation = pinned
        else:
            generation = current_generation()
    return caps, mode, int(generation)


def _message_cap_list(body: dict) -> list:
    from kite_app.scanner_data import normalize_cap_segments

    return normalize_cap_segments(
        body.get("caps") if isinstance(body.get("caps"), list) else None,
        require=True,
    )


def _generation_matches(mode: str, raw) -> bool:
    from kite_app.desk_progress import current_generation

    live = current_generation()
    if raw is None:
        return live == 0
    try:
        got = int(raw)
    except (TypeError, ValueError):
        return False
    if got == live:
        return True
    pinned = _GEN.get(mode)
    return pinned is not None and got == int(pinned)


def _bind_enqueue(mode: str, body: dict) -> None:
    from kite_app.desk_progress import current_generation

    caps = _message_cap_list(body)
    if caps:
        _CAPS_LOCAL.caps = list(caps)
        _CAPS[mode] = list(caps)
    _CAPS_LOCAL.mode = mode
    pinned = _GEN.get(mode)
    _CAPS_LOCAL.generation = int(pinned) if pinned is not None else int(current_generation())


def _clear_enqueue() -> None:
    for name in ("caps", "mode", "generation"):
        if hasattr(_CAPS_LOCAL, name):
            delattr(_CAPS_LOCAL, name)


def _queue_should_wait() -> bool:
    """Sleep the worker only when every read is paused."""
    if not _paused():
        return False
    for mode in _MODES:
        if mode in _PAUSED_MODES:
            continue
        if mode == _MODE and _WORKING and not _FINISHED:
            return False
        snap = _SAVED.get(mode)
        if snap and snap.get("working") and not snap.get("finished"):
            return False
    return True


def start_from_zero(record: Optional[dict], caps: Optional[list[str]] = None, mode: str = "screens") -> dict:
    """Drop this read's progress and start again at the first NSE share.

    TechnicalScan and PaulScan each keep their own names, caps, and queue generation.
    """
    global _FINISHED, _LAST_COUNT, _RUNNING, _SEEN, _SCREENED, _REVIEW_QUEUED, _REVIEWS, _PASSED, _BOOK
    mode = mode if mode in _MODES else "screens"
    from kite_app.desk_progress import bump_generation, clear_activity, resume_scan
    from kite_app.scanner_data import selected_cap_segments, set_cap_segments

    # Restart with an explicit list pins this read. continue_scan passes None and
    # must keep whatever large/mid/small selection is already active.
    with _LOCK:
        _switch_to_locked(mode)
        _PAUSED_MODES.discard(mode)
        if caps is None:
            chosen = list(selected_cap_segments())
        else:
            chosen = list(set_cap_segments(caps))
        _CAPS[mode] = list(chosen)
        missing = not record or not record.get("api_key") or not record.get("access_token")
        if missing:
            _set_working(False, _login_note())
        else:
            _GEN[mode] = bump_generation()
            if not _other_working(mode):
                clear_activity()
            _SEEN = set()
            _SCREENED = set()
            _REVIEW_QUEUED = set()
            _REVIEWS = {}
            _PASSED = {}
            _LAST_COUNT = -1
            _FINISHED = False
            _BOOK = {"scanned": 0, "accepted": 0, "setups": [], "sell_calls": [], "vetoes": []}
            _RUNNING = False
    if missing:
        return public_snapshot()
    # Leave saved prices in place while the other read is still using them.
    if not _other_working(mode):
        try:
            from kite_app.scan_jobs import forget_saved_scans

            forget_saved_scans()
        except Exception:
            logger.info("saved scan coverage was not cleared")
    resume_scan()
    labels = ", ".join(chosen)
    _set_working(True, f"Starting again from the first NSE share ({labels}).")
    snapshot = public_snapshot()
    threading.Thread(
        target=_begin_again,
        args=(record, mode, list(chosen), int(_GEN[mode])),
        daemon=True,
    ).start()
    return snapshot


def _begin_again(record: dict, mode: Optional[str] = None, caps: Optional[list] = None, generation: Optional[int] = None) -> None:
    """Start the read after coverage was cleared on the request thread."""
    if mode in _MODES:
        _CAPS_LOCAL.mode = mode
    if caps:
        _CAPS_LOCAL.caps = list(caps)
    if generation is not None:
        _CAPS_LOCAL.generation = int(generation)
    try:
        with _LOCK:
            if mode in _MODES:
                _switch_to_locked(mode)
        _launch(record)
    except Exception:
        logger.info("scan was not started")
    finally:
        _clear_enqueue()


def _adopt_mode(body: dict) -> None:
    """A same-generation message carries the desk mode so a worker scores the 30 points only."""
    global _MODE
    raw = body.get("mode")
    if raw in _MODES:
        _MODE = raw


def _message_is_current(body: dict) -> bool:
    """Drop older-generation work for this read. The other read keeps its own generation.

    SQS workers may not have seen the HTTP Start-from-zero yet. When the
    generation matches, adopt the caps stamped on the message so a large-only
    restart cannot keep screening mid/small on a stale worker.
    """
    from kite_app.scanner_data import selected_cap_segments, set_cap_segments

    mode = _scan_mode(body)
    if not _generation_matches(mode, body.get("generation")):
        return False
    message_caps = _message_cap_list(body)
    if not message_caps:
        return False
    _CAPS[mode] = list(message_caps)
    # A second live read must not have its universe rewritten by this message.
    if not _other_working(mode) and set(message_caps) != set(selected_cap_segments()):
        set_cap_segments(message_caps)
    _adopt_mode(body)
    return True


def continue_scan(record: Optional[dict]) -> dict:
    """Older clients use this path. It starts again from the first name."""
    return start_from_zero(record)


def public_snapshot() -> dict:
    """Both reads. A poll that arrives during a model call still sees the last lines."""
    owns = _LOCK.acquire(blocking=False)
    try:
        if not owns and _LAST_SNAPSHOT:
            return copy.deepcopy(_LAST_SNAPSHOT)
        return _build_public_snapshot()
    finally:
        if owns:
            _LOCK.release()


def _build_public_snapshot() -> dict:
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
            "paused": current_scan_mode() in _PAUSED_MODES or _paused(),
            "finished": _FINISHED,
            "caps": selected_cap_segments(),
            "mode": current_scan_mode(),
        }
        focus = _FOCUS
    progress = _scan_progress()
    if book["finished"]:
        # One clear outcome line. Never mix "finished" with "% remaining" chatter.
        note = focus or _finished_note()
        book["activity"] = [{"text": note, "state": "done"}]
        book["progress"] = None
        book["universe_note"] = note
        return _with_runs(book)
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
    return _with_runs(book)


def _saved_run(mode: str) -> dict:
    snap = _SAVED.get(mode)
    paused = mode in _PAUSED_MODES
    if not snap:
        return {
            "scanned": 0,
            "accepted": 0,
            "setups": [],
            "sell_calls": [],
            "vetoes": [],
            "passed": [],
            "working": False,
            "paused": paused,
            "finished": False,
            "caps": list(_CAPS.get(mode) or []),
            "mode": mode,
            "activity": [],
            "progress": None,
            "universe_note": "",
        }
    working = bool(snap.get("working")) and not snap.get("finished") and not paused
    focus = str(snap.get("focus") or "")
    book = snap.get("book") or {}
    passed = snap.get("passed") or {}
    return {
        "scanned": int(book.get("scanned") or 0),
        "accepted": int(book.get("accepted") or 0),
        "setups": copy.deepcopy(book.get("setups") or []),
        "sell_calls": copy.deepcopy(book.get("sell_calls") or []),
        "vetoes": copy.deepcopy(book.get("vetoes") or []),
        "passed": [
            dict(item)
            for item in sorted(passed.values(), key=lambda row: str(row.get("symbol") or ""))
        ],
        "working": working,
        "paused": paused,
        "finished": bool(snap.get("finished")),
        "caps": list(_CAPS.get(mode) or []),
        "mode": mode,
        "progress": None if snap.get("finished") else snap.get("progress"),
        "universe_note": focus,
        "activity": [{"text": focus, "state": "active" if working else "done"}] if focus else [],
    }


def _with_runs(book: dict) -> dict:
    """Attach both reads. The top-level fields stay the read this worker is on."""
    global _LAST_SNAPSHOT
    mode = book.get("mode") if book.get("mode") in _MODES else current_scan_mode()
    other = _other_mode(mode)
    book["runs"] = {
        mode: {key: book[key] for key in book if key != "runs"},
        other: _saved_run(other),
    }
    _LAST_SNAPSHOT = book
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
        _set_focus(f"{int(book['accepted'])} names passed every screen. The model is scoring the 30-point framework.")
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
        _set_focus(f"Grok is searching Screener and scoring the 30-point framework for {symbol}.")
        review_setups([item])
        if _model_still_waiting(item):
            continue
        _REVIEWS[_review_key(item)] = {key: item.get(key) for key in _STAMP}
        if item.get("ai_decision") == "buy":
            _set_focus(f"{symbol} is approved. It is ready for a Zerodha buy GTT.")
        elif item.get("ai_decision") == "sell":
            _set_focus(f"{symbol} is a sell call. It is not sent as an order.")


def _load_stocks() -> list[dict]:
    from kite_app.algo_layers import combine_books
    from kite_app.scan_jobs import latest_crossover_signals
    from kite_app.scanner_data import listed_cap_symbols
    from kite_app.signals_cache import history_by_ticker

    signals = latest_crossover_signals()
    remembered = history_by_ticker([signal["symbol"] for signal in signals]) if signals else []
    stocks = combine_books([], signals, remembered)
    try:
        allowed = {symbol.upper() for symbol in listed_cap_symbols(_active_caps())}
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
        from kite_app.scanner_data import listed_cap_symbols

        return max(baseline, len(listed_cap_symbols(_active_caps())))
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
        if mode == "screen" or str(mode).startswith("screen:"):
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
        screen_key = f"screen:{current_scan_mode()}"
        is_screen = mode == "screen" or mode == screen_key or str(mode).startswith("screen:")
        if is_screen and mode != screen_key and screen_key in scan_status():
            continue
        chosen = payload
        if is_screen:
            finished_screen = payload
        if not row.get("running"):
            continue
        if is_screen:
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
    threading.Thread(
        target=_loop,
        kwargs={
            "mode": getattr(_CAPS_LOCAL, "mode", None),
            "caps": list(getattr(_CAPS_LOCAL, "caps", None) or []),
            "generation": getattr(_CAPS_LOCAL, "generation", None),
        },
        daemon=True,
    ).start()


def handle_message(body: dict) -> None:
    """Run one queued batch for its own read. The other read stays parked."""
    mode = _scan_mode(body)
    _LOCK.acquire()
    try:
        _switch_to_locked(mode)
        if mode in _PAUSED_MODES:
            return
        if _paused() and not _other_working(mode):
            return
        if not _message_is_current(body):
            # Stale large/mid/small work must not mutate this read's selection.
            return
        _bind_enqueue(mode, body)
        kind = str(body.get("kind") or "")
        if kind == "equity_pass":
            _handle_pass(body)
        elif kind == "screen":
            _handle_screen(body)
        elif kind == "review":
            _handle_review(body)
    finally:
        _clear_enqueue()
        _LOCK.release()


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
        _set_working(False, "The equity read is still going. Open TechnicalScan again to continue.")
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
        waiting = (
            "Scoring the 30-point framework for the selected caps."
            if current_scan_mode() == "wealth30"
            else "Scoring the 30-point framework for names that passed every screen."
        )
        _set_working(True, waiting)
        return
    _mark_finished(_finished_note())


def _scan_mode(body: dict) -> str:
    raw = body.get("mode")
    if raw in _MODES:
        return raw
    return current_scan_mode()


def _framework_candidate(stock: dict) -> dict:
    """One name for the 30-point read. A price-screen miss still goes to the model."""
    from kite_app.algo_layers import evaluate_stock

    decision = evaluate_stock(stock)
    if decision:
        decision["reason"] = "In the 30-point read."
        return decision
    candles = stock.get("candles") or []
    last = float(candles[-1]["close"]) if candles else 0.0
    symbol = str(stock.get("symbol") or "").upper()
    return {
        "symbol": symbol,
        "company_name": str(stock.get("company_name") or symbol),
        "exchange": stock.get("exchange") or "NSE",
        "last_close": last or None,
        "entry": last,
        "stop": round(last * 0.95, 2) if last else 0,
        "target": round(last * 1.1, 2) if last else 0,
        "gtt_tradable": last > 0,
        "reason": "In the 30-point read.",
        "desk": {"book_call": "buy"},
        "traps": [],
    }


def _queue_framework(body: dict, symbols: list[str], stocks: list[dict]) -> None:
    """Send every name in the ticked caps to the 30-point framework."""
    rows = [_framework_candidate(stock) for stock in stocks if stock.get("symbol")]
    _note_passed(rows)
    user = str(body.get("platform_user_id") or "")
    review_symbols = []
    for item in rows:
        symbol = str(item.get("symbol") or "")
        if symbol and _review_key(item) not in _REVIEWS and symbol not in _REVIEW_QUEUED:
            review_symbols.append(symbol)
    if review_symbols and user:
        from kite_app.equity_queue import enqueue_reviews

        if enqueue_reviews(user, review_symbols) < 1:
            raise RuntimeError("review batches were not queued")
        _REVIEW_QUEUED.update(review_symbols)
    done = _mark_screened(symbols)
    with _LOCK:
        _BOOK["scanned"] = int(_BOOK["scanned"]) + len(symbols)
        _BOOK["accepted"] = int(_BOOK["accepted"]) + len(rows)
    _note_screen_progress(done, _screen_total(max(done, len(_saved_symbols()))))
    _set_working(True, _count_line())
    if review_symbols:
        _set_focus(f"Queued {', '.join(review_symbols[:5])} for the 30-point framework.")
    _finish_if_idle()


def _handle_screen(body: dict) -> None:
    if _FINISHED:
        return
    from kite_app.scanner_data import filter_symbols_to_caps

    raw_symbols = [str(symbol).upper() for symbol in body.get("symbols") or [] if str(symbol).strip()]
    symbols = filter_symbols_to_caps(raw_symbols, _active_caps())
    if not symbols:
        # Cap filter dropped the batch; still clear the queued SEEN entries so finish can run.
        _mark_screened(raw_symbols)
        _finish_if_idle()
        return
    wanted = set(symbols)
    stocks = [row for row in _load_stocks() if str(row.get("symbol") or "").upper() in wanted]
    if _scan_mode(body) == "wealth30":
        _queue_framework(body, symbols, stocks)
        return
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
    review_symbols = filter_symbols_to_caps(review_symbols, _active_caps())
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
        _set_focus(f"Queued {', '.join(review_symbols[:5])} for the 30-point framework.")
    _finish_if_idle()


def _handle_review(body: dict) -> None:
    if _FINISHED:
        return
    from kite_app.scanner_data import filter_symbols_to_caps

    symbol = str(body.get("symbol") or "").upper()
    if not symbol or filter_symbols_to_caps([symbol], _active_caps()) != [symbol]:
        _REVIEW_QUEUED.discard(symbol)
        _finish_if_idle()
        return
    stocks = [row for row in _load_stocks() if str(row.get("symbol") or "").upper() == symbol]
    if not stocks:
        _REVIEW_QUEUED.discard(symbol)
        _set_focus(f"{symbol} is waiting for saved prices.")
        _finish_if_idle()
        return
    if _scan_mode(body) == "wealth30":
        rows = [_framework_candidate(stocks[0])]
    else:
        from kite_app.algo_layers import select_setups

        book = select_setups(stocks, review=False)
        rows = [*book["setups"], *book["sell_calls"]]
    if not rows:
        _REVIEW_QUEUED.discard(symbol)
        _finish_if_idle()
        return
    _review_rows(rows)
    if any(_model_still_waiting(item) for item in rows):
        if _requeue_model(body, symbol):
            return
    _remember_setups(rows)
    _mark_passed_status(rows)
    _REVIEW_QUEUED.discard(symbol)
    buys = [str(item.get("symbol") or "") for item in rows if item.get("ai_decision") == "buy"]
    if buys:
        _set_focus(f"{', '.join(buys)} is approved and ready for a Zerodha buy GTT.")
    else:
        veto = next((item for item in rows if item.get("ai_reason")), None)
        if veto:
            lead = (
                f"{veto.get('symbol')} was scored on the 30-point framework."
                if _scan_mode(body) == "wealth30"
                else f"{veto.get('symbol')} passed every screen, but the model did not approve a buy."
            )
            _set_focus(f"{lead} {veto.get('ai_reason')}")
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


def _model_still_waiting(item: dict) -> bool:
    """A timeout or a full Grok queue is not a 30-point score."""
    if str(item.get("ai_decision") or "") != "unavailable":
        return False
    reason = str(item.get("ai_reason") or "").lower()
    return any(phrase in reason for phrase in ("timed out", "timeout", "capacity", "not a stock rejection"))


def _requeue_model(body: dict, symbol: str) -> bool:
    """Put the name back on the queue and keep the read open until Grok scores it."""
    attempt = int(body.get("attempt") or 0) + 1
    user = str(body.get("platform_user_id") or "")
    if attempt > _MODEL_RETRY_LIMIT or not user:
        return False
    from kite_app.equity_queue import enqueue_reviews

    if enqueue_reviews(user, [symbol], delay_seconds=min(30 * attempt, 120), attempt=attempt) < 1:
        raise RuntimeError("model review was not requeued")
    with _LOCK:
        row = _PASSED.get(symbol)
        if row:
            row["status"] = "waiting"
    _set_working(
        True,
        f"Grok is still searching Screener and scoring the 30-point framework for {symbol}. "
        f"The read stays open until every passed name is scored ({attempt} of {_MODEL_RETRY_LIMIT}).",
    )
    return True


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
                row["reason"] = str(item.get("ai_reason") or "").strip()


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
        status = scan_status()
        row = status.get(f"screen:{current_scan_mode()}") or status.get("screen") or {}
        total = int(row.get("total") or 0)
    total = max(int(total), int(done))
    if total <= 0:
        return
    note_scan(
        f"screen:{current_scan_mode()}",
        done,
        total,
        0,
        done < total,
        label="names",
        action="screened",
    )
    if not _other_working(current_scan_mode()):
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


def _passed_reasons(passed: list[dict]) -> list[str]:
    """One line per name that was scored or left unanswered, keeping the model's own words."""
    lines = []
    for item in sorted(passed, key=lambda row: str(row.get("symbol") or "")):
        symbol = str(item.get("symbol") or "")
        status = str(item.get("status") or "")
        if not symbol or status in {"", "waiting", "buy"}:
            continue
        reason = str(item.get("reason") or "").strip()
        if not reason and status == "stand_aside":
            reason = "The model did not approve a buy."
        if not reason:
            reason = "The model did not return a score."
        lines.append(f"{symbol}: {reason}")
    return lines


def _finished_note() -> str:
    with _LOCK:
        screened = len(_SCREENED)
        accepted = int(_BOOK["accepted"] or 0)
        buys = len(_BOOK["setups"])
        vetoes = [dict(item) for item in _BOOK.get("vetoes") or []]
        passed = [dict(item) for item in _PASSED.values()]
    from kite_app.scanner_data import cap_segment_note

    universe = cap_segment_note()
    if buys:
        return f"The {universe} read is finished. {buys} approved buy{'s' if buys != 1 else ''} ready."
    scored = _passed_reasons(passed)
    if scored and accepted:
        return f"The {universe} read is finished. " + " ".join(scored)
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
        mode_name = current_scan_mode()
        other_live = _other_working(mode_name)
    # Drop leftover "% remaining" lines so the desk only shows the outcome.
    # Leave the other read's meter alone while it is still running.
    if not other_live:
        clear_activity()
    # Snap the screen meter to 100% so a finished read never sits at "12% remaining".
    if screened > 0:
        note_scan(f"screen:{mode_name}", screened, screened, 0, False, label="names", action="screened")
        if not other_live:
            note_scan("screen", screened, screened, 0, False, label="names", action="screened")
    # Stop leftover price-scan meters so the desk does not show "5 of 495" after a finished large-cap read.
    if not other_live:
        for mode, row in scan_status().items():
            if mode == "screen" or str(mode).startswith("screen:") or not row.get("running"):
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
        if _queue_should_wait():
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


def _loop(mode: Optional[str] = None, caps: Optional[list] = None, generation: Optional[int] = None) -> None:
    global _RUNNING
    mode = mode if mode in _MODES else current_scan_mode()
    if caps:
        _CAPS_LOCAL.caps = list(caps)
    _CAPS_LOCAL.mode = mode
    if generation is not None:
        _CAPS_LOCAL.generation = int(generation)
    token = _GEN.get(mode)
    started = time.monotonic()
    try:
        while time.monotonic() - started < 45 * 60:
            if mode in _PAUSED_MODES or (_paused() and not _other_working(mode)):
                with _LOCK:
                    if _MODE != mode:
                        _switch_to_locked(mode)
                _set_working(False, _STOP_NOTE)
                return
            if _GEN.get(mode) != token:
                return
            with _LOCK:
                if _MODE != mode:
                    _switch_to_locked(mode)
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
                    _set_working(True, "Scoring the 30-point framework for names that passed every screen.")
                else:
                    _finish_if_idle()
                    if _FINISHED:
                        return
            time.sleep(5)
        _set_working(False, "The equity read is still going. Open TechnicalScan again to continue.")
    finally:
        with _LOCK:
            if _MODE == mode:
                _RUNNING = False
            elif mode in _SAVED:
                _SAVED[mode]["running"] = False


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
    _touch_snapshot()


def _set_focus(focus: str) -> None:
    global _FOCUS
    with _LOCK:
        _FOCUS = focus
    if _FINISHED and "% remaining." in focus:
        return
    _note_activity_line(focus)
    _touch_snapshot()


def _touch_snapshot() -> None:
    """Keep a copy a poll can read while this read holds the worker."""
    global _LAST_SNAPSHOT, _TOUCHING
    if _TOUCHING:
        return
    _TOUCHING = True
    try:
        _LAST_SNAPSHOT = _build_public_snapshot()
    except Exception:
        logger.info("scan snapshot was not stored")
    finally:
        _TOUCHING = False


def _note_activity_line(focus: str) -> None:
    from kite_app.desk_progress import note_activity

    note_activity(focus)


def _review_key(item: dict) -> str:
    return f"{item.get('symbol')}|{item.get('entry')}|{item.get('last_close')}"
