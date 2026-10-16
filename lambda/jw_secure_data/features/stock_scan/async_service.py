"""Async stock scan jobs — enqueue via Lambda async invoke, poll via S3 job store."""

from __future__ import annotations

import json
import os
from typing import Any

from features.stock_scan import job_store, service


def _enqueue_worker(job_id: str, *, function_name: str | None) -> None:
    payload = {"internal": "stock_scan_job", "jobId": job_id}
    if os.environ.get("ENVIRONMENT", "").lower() == "local":
        import threading

        threading.Thread(target=execute_job, args=(job_id,), daemon=True).start()
        return

    import boto3

    target = function_name or os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "jw_secure_data_dev")
    boto3.client("lambda").invoke(
        FunctionName=target,
        InvocationType="Event",
        Payload=json.dumps(payload).encode("utf-8"),
    )


def start_async_scan(payload: dict[str, Any], *, function_name: str | None = None) -> dict[str, Any]:
    symbols = service.resolve_scan_symbols(payload)
    job = job_store.create_job(payload, total_symbols=len(symbols))
    _enqueue_worker(job["jobId"], function_name=function_name)
    return {
        "jobId": job["jobId"],
        "status": job["status"],
        "progress": job["progress"],
    }


def get_job_status(job_id: str) -> dict[str, Any] | None:
    job = job_store.get_job(job_id)
    if job is None:
        return None
    return job_store.public_job_view(job)


def execute_job(job_id: str) -> None:
    job = job_store.get_job(job_id)
    if job is None or job.get("status") not in {"pending"}:
        return

    job_store.update_job(job_id, status="running")
    payload = job.get("request") or {}
    total = int((job.get("progress") or {}).get("total") or 0)

    def on_progress(completed: int, scan_total: int) -> None:
        job_store.update_job(
            job_id,
            progress={"total": scan_total or total, "completed": completed},
        )

    try:
        result = service.run_scan(payload, on_progress=on_progress)
        job_store.update_job(
            job_id,
            status="complete",
            result=result,
            progress={
                "total": result.get("scannedCount", total),
                "completed": result.get("scannedCount", total),
            },
        )
    except Exception as exc:
        job_store.update_job(job_id, status="failed", error=f"{type(exc).__name__}: {exc}")
