"""Persist stock scan jobs (S3 in AWS, local files for serve.py)."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

JOBS_PREFIX = "stock-scan-jobs"
LOCAL_JOBS_DIR = Path("/tmp/jakshwealth-stock-scan-jobs")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jobs_bucket() -> str:
    return os.environ.get(
        "STOCK_SCAN_JOBS_BUCKET",
        os.environ.get("LAMBDA_ARTIFACT_BUCKET", "jakshwealth-artifacts-dev-aps2"),
    )


def _use_local_store() -> bool:
    return os.environ.get("ENVIRONMENT", "").lower() == "local"


def _local_job_path(job_id: str) -> Path:
    LOCAL_JOBS_DIR.mkdir(parents=True, exist_ok=True)
    return LOCAL_JOBS_DIR / f"{job_id}.json"


def _s3_key(job_id: str) -> str:
    return f"{JOBS_PREFIX}/{job_id}.json"


def _read_job(job_id: str) -> dict[str, Any] | None:
    if _use_local_store():
        path = _local_job_path(job_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    import boto3
    from botocore.exceptions import ClientError

    client = boto3.client("s3")
    try:
        obj = client.get_object(Bucket=_jobs_bucket(), Key=_s3_key(job_id))
        return json.loads(obj["Body"].read().decode("utf-8"))
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
            return None
        raise


def _write_job(job: dict[str, Any]) -> None:
    payload = json.dumps(job, default=str)
    if _use_local_store():
        _local_job_path(job["jobId"]).write_text(payload, encoding="utf-8")
        return

    import boto3

    boto3.client("s3").put_object(
        Bucket=_jobs_bucket(),
        Key=_s3_key(job["jobId"]),
        Body=payload.encode("utf-8"),
        ContentType="application/json",
    )


def create_job(request: dict[str, Any], *, total_symbols: int) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    now = _utc_now()
    job = {
        "jobId": job_id,
        "status": "pending",
        "createdAt": now,
        "updatedAt": now,
        "request": request,
        "progress": {"total": total_symbols, "completed": 0},
        "result": None,
        "error": None,
    }
    _write_job(job)
    return job


def get_job(job_id: str) -> dict[str, Any] | None:
    return _read_job(job_id)


def update_job(job_id: str, **fields: Any) -> dict[str, Any] | None:
    job = _read_job(job_id)
    if job is None:
        return None
    job.update(fields)
    job["updatedAt"] = _utc_now()
    _write_job(job)
    return job


def public_job_view(job: dict[str, Any]) -> dict[str, Any]:
    view: dict[str, Any] = {
        "jobId": job["jobId"],
        "status": job["status"],
        "progress": job.get("progress") or {"total": 0, "completed": 0},
        "createdAt": job.get("createdAt"),
        "updatedAt": job.get("updatedAt"),
    }
    if job.get("error"):
        view["error"] = job["error"]
    if job.get("status") == "complete" and job.get("result"):
        view.update(job["result"])
    return view
