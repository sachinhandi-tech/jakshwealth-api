"""In-memory progress for the equity read. The final-list request only reads this."""

from __future__ import annotations

import threading

_LOCK = threading.Lock()
_SCANS: dict[str, dict] = {}
_FILL = {"saved": 0, "universe": 0, "active": False}
_PAUSED = False
_ACTIVITY: list[str] = []
_GENERATION = 0


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


def current_generation() -> int:
    with _LOCK:
        return _GENERATION


def bump_generation() -> int:
    """Ignore a scan that was already running when the desk starts again from zero."""
    global _GENERATION
    with _LOCK:
        _GENERATION += 1
        return _GENERATION


def clear_activity() -> None:
    with _LOCK:
        _ACTIVITY.clear()
        _SCANS.clear()


def note_activity(text: str) -> None:
    """Remember one short line the desk can show. Repeated lines stay as one."""
    line = " ".join(str(text or "").split())
    if not line:
        return
    with _LOCK:
        if _ACTIVITY and _ACTIVITY[-1] == line:
            return
        _ACTIVITY.append(line)
        del _ACTIVITY[:-8]


def activity_status() -> list[str]:
    with _LOCK:
        return list(_ACTIVITY)


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
