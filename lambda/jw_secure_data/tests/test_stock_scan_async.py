import json

from features.stock_scan import async_service, job_store, service


def test_resolve_scan_symbols_midcap_full():
    symbols = service.resolve_scan_symbols({"universeSegment": "midcap"})
    assert len(symbols) == 150


def test_async_job_lifecycle_local(monkeypatch, tmp_path):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setattr(job_store, "LOCAL_JOBS_DIR", tmp_path)

    enqueued: list[str] = []

    def fake_enqueue(job_id: str, *, function_name: str | None = None) -> None:
        enqueued.append(job_id)
        async_service.execute_job(job_id)

    monkeypatch.setattr(async_service, "_enqueue_worker", fake_enqueue)

    payload = {
        "symbols": ["RELIANCE"],
        "minScore": 80,
        "strictRsi30": False,
        "sleep": 0,
        "maxWorkers": 1,
    }
    started = async_service.start_async_scan(payload)
    assert started["status"] == "pending"
    assert len(enqueued) == 1

    job = async_service.get_job_status(started["jobId"])
    assert job is not None
    assert job["status"] == "complete"
    assert job["scannedCount"] == 1
    assert "rankedCandidates" in job


def test_public_job_view_hides_request_payload(monkeypatch, tmp_path):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setattr(job_store, "LOCAL_JOBS_DIR", tmp_path)

    job = job_store.create_job({"universeSegment": "midcap"}, total_symbols=150)
    view = job_store.public_job_view(job)
    assert view["jobId"] == job["jobId"]
    assert "request" not in view
