"""File-backed Kite session so local restarts do not require a new login.

On Lambda the file is under /tmp and is not shared. When a bucket is set, the
same JSON is stored in S3 so every container reuses the access token.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Outside the Python package tree so uvicorn --reload does not restart when this file is written.
# Lambda sets KITE_SESSION_PATH to /tmp because the deployment package is read-only.
DEFAULT_SESSION_PATH = Path(
    os.environ.get("KITE_SESSION_PATH")
    or (Path(__file__).resolve().parent.parent / ".kite" / "session.json")
)

SESSION_FIELDS = ("api_key", "access_token", "user_id", "user_name", "saved_at")


class SessionStore:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or Path(
            os.environ.get("KITE_SESSION_PATH")
            or (Path(__file__).resolve().parent.parent / ".kite" / "session.json")
        )

    def load(self) -> Optional[dict]:
        state, remote = _read_s3()
        if state == "ok" and remote is not None:
            self._write_local(remote)
            return remote
        if state == "cleared":
            self._remove_local()
            return None
        return self._read_local()

    def save(self, record: dict) -> None:
        payload = {field: record.get(field) for field in SESSION_FIELDS}
        self._write_local(payload)
        _write_s3(payload)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        _delete_s3()

    def _remove_local(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            return

    def _read_local(self) -> Optional[dict]:
        if not self.path.is_file():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return _session_record(data)

    def _write_local(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)


def _session_record(data) -> Optional[dict]:
    if not isinstance(data, dict):
        return None
    api_key = str(data.get("api_key") or "").strip()
    access_token = str(data.get("access_token") or "").strip()
    if not api_key or not access_token:
        return None
    return {field: data.get(field) for field in SESSION_FIELDS}


def _session_bucket() -> str:
    return os.environ.get("KITE_SESSION_BUCKET", "").strip() or os.environ.get("SCANNER_CACHE_BUCKET", "").strip()


def _session_key() -> str:
    return os.environ.get("KITE_SESSION_KEY", "kite-session/session.json").strip() or "kite-session/session.json"


def _read_s3() -> tuple[str, Optional[dict]]:
    bucket = _session_bucket()
    if not bucket:
        return "absent", None
    try:
        import boto3

        body = boto3.client("s3").get_object(Bucket=bucket, Key=_session_key())["Body"].read()
        record = _session_record(json.loads(body))
    except Exception as exc:
        code = ""
        response = getattr(exc, "response", None)
        if isinstance(response, dict):
            code = str((response.get("Error") or {}).get("Code") or "")
        if code in {"NoSuchKey", "404", "NotFound"}:
            return "missing", None
        return "error", None
    if record is None:
        return "cleared", None
    return "ok", record


def _write_s3(payload: dict) -> None:
    bucket = _session_bucket()
    if not bucket:
        return
    try:
        import boto3

        boto3.client("s3").put_object(
            Bucket=bucket,
            Key=_session_key(),
            Body=json.dumps(payload).encode("utf-8"),
            ContentType="application/json",
        )
    except Exception:
        return


def _delete_s3() -> None:
    """Replace the shared session so another container does not reload it from a local file."""
    bucket = _session_bucket()
    if not bucket:
        return
    try:
        import boto3

        boto3.client("s3").put_object(
            Bucket=bucket,
            Key=_session_key(),
            Body=b"{}",
            ContentType="application/json",
        )
    except Exception:
        return
