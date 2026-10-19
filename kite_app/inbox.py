"""In-memory inbox for algo signals. Entries reset when the process restarts."""

from __future__ import annotations

from collections import deque

_inbox: deque[dict] = deque(maxlen=50)


def remember(payload: dict) -> None:
    _inbox.appendleft(payload)


def recent_signals() -> list[dict]:
    return list(_inbox)
