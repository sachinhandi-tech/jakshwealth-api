"""In-memory progress for the equity read. The final-list request only reads this."""

from __future__ import annotations

import threading

_LOCK = threading.Lock()
_SCANS: dict[str, dict] = {}
_FILL = {"saved": 0, "universe": 0, "active": False}
_PAUSED = False


def scan_paused() -> bool:
    with _LOCK:
        return _PAUSED


def pause_scan() -> None:
    """Stop new scan work. Names already saved stay where they are."""
    global _PAUSED
    with _LOCK:
        _PAUSED = True
        for row in _SCANS.values():
            row["running"] = False
        _FILL["active"] = False


def resume_scan() -> None:
    global _PAUSED
    with _LOCK:
        _PAUSED = False


def note_scan(mode: str, done: int, total: int, signals: int, running: bool) -> None:
    with _LOCK:
        if _PAUSED:
            running = False
        _SCANS[str(mode)] = {
            "done": int(done),
            "total": int(total),
            "signals": int(signals),
            "running": bool(running),
        }


def scan_status() -> dict:
    with _LOCK:
        return {key: dict(value) for key, value in _SCANS.items()}


def note_fill(saved: int, universe: int, active: bool) -> None:
    with _LOCK:
        if _PAUSED:
            active = False
        _FILL["saved"] = int(saved)
        _FILL["universe"] = int(universe)
        _FILL["active"] = bool(active)


def fill_status() -> dict:
    with _LOCK:
        return dict(_FILL)
