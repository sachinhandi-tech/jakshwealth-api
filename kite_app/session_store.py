"""File-backed Kite session so local restarts do not require a new login."""

from __future__ import annotations

import json
import os
from pathlib import Path

# Outside the Python package tree so uvicorn --reload does not restart when this file is written.
DEFAULT_SESSION_PATH = Path(__file__).resolve().parent.parent / ".kite" / "session.json"

SESSION_FIELDS = ("api_key", "access_token", "user_id", "user_name", "saved_at")


class SessionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_SESSION_PATH

    def load(self) -> dict | None:
        if not self.path.is_file():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        api_key = str(data.get("api_key") or "").strip()
        access_token = str(data.get("access_token") or "").strip()
        if not api_key or not access_token:
            return None
        return {field: data.get(field) for field in SESSION_FIELDS}

    def save(self, record: dict) -> None:
        payload = {field: record.get(field) for field in SESSION_FIELDS}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            return
