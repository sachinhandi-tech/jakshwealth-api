"""API Gateway entry point for the Kite FastAPI app."""

from __future__ import annotations

import os

os.environ.setdefault("KITE_SESSION_PATH", "/tmp/kite-session.json")
os.environ.setdefault("KITE_DB_SECRET_ID", "jakshwealth/dev/postgres")

from kite_app.models import load_platform_config

load_platform_config()

from kite_app.apigw import normalize_event
from kite_app.main import app
from mangum import Mangum

_asgi = Mangum(app, lifespan="off")


def handler(event, context):
    if isinstance(event, dict) and event.get("source") == "kite-scan":
        from kite_app.scan_jobs import run_scan_job

        run_scan_job(str(event.get("job_id") or ""))
        return {"ok": True}
    return _asgi(normalize_event(event or {}), context)
