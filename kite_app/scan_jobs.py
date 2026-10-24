"""Run scans with intelligent historical data caching (95%+ API reduction)."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from kiteconnect import KiteConnect
from kiteconnect.exceptions import KiteException

from kite_app.models import SignalScanJob, get_sessionmaker, load_platform_config
from kite_app.session_manager import encrypt_access_token
from kite_app.signals import SignalScanError
from kite_app.signals_parallel_cached import scan_nifty100_parallel_cached

logger = logging.getLogger("kite_app.scan")
ASYNC_SCAN_BUDGET_SECONDS = 600
_MEMORY: dict[str, dict] = {}
_LISTS: dict[str, dict] = {}
_PUBLIC_FIELDS = (
    "scan_mode",
    "ma_type",
    "short_type",
    "long_type",
    "trend_window",
    "short_window",
    "long_window",
    "lookback_days",
    "universe",
    "scanned",
    "skipped",
    "signals",
    "scan_all_nse",
    "book",
    "empty_book",
)


_FILLING = False
_EQUITY_NOTE = "The backend is reading NSE equities and front-month commodity futures. A name appears in its list after it passes the moving-average crossover, the price and volume expansion, and the RSI momentum and ATR screen."
_BOOKS = (
    ("equity", 2500),
    ("commodity_future", 200),
)


def ensure_listed_equity_scan(record: Optional[dict]) -> str:
    """Start the next unread book. One book runs at a time so Zerodha is not flooded."""
    from kite_app.desk_progress import scan_paused

    if scan_paused():
        return ""
    if not record or not record.get("api_key") or not record.get("access_token"):
        return ""
    try:
        for book, cap in _BOOKS:
            if _book_running(book):
                if _scan_is_live(book):
                    return _EQUITY_NOTE
                if not _release_stale_run(book):
                    return _EQUITY_NOTE
            if _book_covered(book):
                continue
            params = _book_params(book, "price", 200, 200, 120, cap)
            params["full_pass"] = True
            params["short_window"] = 20
            params["short_type"] = "ema"
            from kite_app.desk_progress import note_activity

            label = "NSE equities" if book == "equity" else "Commodity futures"
            note_activity(f"Starting {label}.")
            enqueue_scan(record, params)
            return _EQUITY_NOTE
    except Exception:
        logger.info("listed equity scan was not started")
        return ""
    return ""


def _book_params(book: str, scan_mode: str, long_window: int, trend_window: int, lookback_days: int, max_stocks: int) -> dict:
    return {
        "scan_mode": scan_mode,
        "book": book,
        "ma_type": "ema" if scan_mode == "crossover" else "sma",
        "short_type": "ema" if scan_mode == "crossover" else "sma",
        "long_type": "sma",
        "short_window": 20 if scan_mode == "crossover" else 2,
        "long_window": long_window,
        "trend_window": trend_window,
        "lookback_days": lookback_days,
        "max_stocks": max_stocks,
        "scan_all_nse": True,
    }


def _equity_scan_active() -> bool:
    if not _use_database():
        return any(_is_equity_request(row.get("request_json")) and row.get("status") == "running" for row in _MEMORY.values())
    db = get_sessionmaker()()
    try:
        jobs = db.query(SignalScanJob).filter(SignalScanJob.status == "running").all()
    finally:
        db.close()
    return any(_is_equity_request(job.request_json) for job in jobs)


def _is_equity_request(raw: Optional[str]) -> bool:
    try:
        params = json.loads(raw or "")
    except json.JSONDecodeError:
        return False
    return bool(params.get("scan_all_nse"))


def equity_work_pending() -> bool:
    """True while a full equity read or candle fill is still unfinished."""
    return _FILLING or _equity_scan_active() or not _equity_scan_covers_universe()


def _equity_scan_covers_universe() -> bool:
    return all(_book_covered(book) for book, _cap in _BOOKS)


def _book_covered(book: str) -> bool:
    saved = _stored_lists()
    for kind in ("short", "long"):
        key = kind if book == "equity" else f"{book}-{kind}"
        result = saved.get(key) or {}
        if result.get("empty_book") is True:
            continue
        if result.get("scan_all_nse") is not True:
            return False
        universe = int(result.get("universe") or 0)
        covered = int(result.get("scanned") or 0) + int(result.get("skipped") or 0)
        if universe <= 0 or covered < universe:
            return False
    return True


def _scan_is_live(book: str) -> bool:
    from kite_app.desk_progress import scan_status

    for mode, row in scan_status().items():
        name = mode.split(":", 1)[0] if ":" in mode else mode
        if name == book and row.get("running") and int(row.get("total") or 0) > 0:
            return True
    return False


def _release_stale_run(book: str) -> bool:
    """Release a pass whose thread is gone. A live NSE read takes longer than a few minutes, so a young row is left alone."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=1800)
    if not _use_database():
        stale = [
            job_id for job_id, row in _MEMORY.items()
            if row.get("status") == "running" and _request_book(row.get("request_json")) == book
        ]
        for job_id in stale:
            _finish(job_id, "error", None, "The scan stopped before it could report progress.")
        return bool(stale)
    db = get_sessionmaker()()
    try:
        jobs = db.query(SignalScanJob).filter(SignalScanJob.status == "running").all()
    finally:
        db.close()
    released = False
    for job in jobs:
        if _request_book(job.request_json) != book:
            continue
        created = job.created_at
        if created is not None and created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created is not None and created > cutoff:
            return False
        _finish(job.job_id, "error", None, "The scan stopped before it could report progress.")
        released = True
    return released


def _book_running(book: str) -> bool:
    if not _use_database():
        return any(_request_book(row.get("request_json")) == book and row.get("status") == "running" for row in _MEMORY.values())
    db = get_sessionmaker()()
    try:
        jobs = db.query(SignalScanJob).filter(SignalScanJob.status == "running").all()
    finally:
        db.close()
    return any(_request_book(job.request_json) == book for job in jobs)


def _request_book(raw: Optional[str]) -> str:
    try:
        params = json.loads(raw or "")
    except json.JSONDecodeError:
        return ""
    if not params.get("scan_all_nse"):
        return ""
    return str(params.get("book") or "equity")


def _start_cache_fill(record: dict) -> None:
    global _FILLING
    if _FILLING:
        return
    _FILLING = True

    def fill() -> None:
        global _FILLING
        try:
            from kite_app.scanner_data import build_scanner_payload

            kite = KiteConnect(api_key=record["api_key"])
            kite.set_access_token(record["access_token"])
            for _ in range(40):
                from kite_app.desk_progress import scan_paused

                if scan_paused():
                    return
                payload = build_scanner_payload(kite, budget_seconds=45)
                if (payload.get("metadata") or {}).get("complete") is True:
                    return
        except Exception:
            logger.info("equity candle fill stopped")
        finally:
            _FILLING = False
            try:
                from kite_app.desk_progress import fill_status, note_fill

                current = fill_status()
                note_fill(int(current.get("saved") or 0), int(current.get("universe") or 0), False)
            except Exception:
                pass

    threading.Thread(target=fill, args=(), daemon=True).start()


def enqueue_scan(record: dict, params: dict) -> str:
    """Save a running job and start it outside this HTTP request."""
    job_id = uuid.uuid4().hex
    plain = json.dumps({
        "api_key": record["api_key"],
        "access_token": record["access_token"],
    })
    if _use_database():
        blob = encrypt_access_token(plain)
    elif os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "").strip():
        raise SignalScanError("The scan store is not configured.")
    else:
        blob = plain
    _save_new(job_id, params, blob)
    _start(job_id)
    return job_id


def latest_crossover_scans() -> dict:
    """Newest finished short and long moving-average scans. Credentials stay out."""
    found: dict[str, Optional[dict]] = {"short": _cached_list("short"), "long": _cached_list("long")}
    if found["short"] is not None and found["long"] is not None:
        return found
    stored = _stored_lists()
    for kind in ("short", "long"):
        if found[kind] is None and stored.get(kind):
            found[kind] = stored[kind]
            _remember_cache(kind, stored[kind])
    if found["short"] is not None and found["long"] is not None:
        return found
    try:
        rows = _done_scans()
    except Exception:
        logger.info("saved crossover scans could not be read")
        return found
    for row in rows:
        try:
            params = json.loads(row["request_json"])
            result = json.loads(row["result_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(result, dict):
            continue
        kind = _horizon(str(params.get("scan_mode") or result.get("scan_mode") or ""))
        if found[kind] is None:
            public = _public_result(result)
            found[kind] = public
            save_crossover_list(kind, public)
        if found["short"] is not None and found["long"] is not None:
            break
    return found


def save_crossover_list(scan_mode: str, result: dict) -> None:
    """Store one horizon for the final call. A cache miss still leaves the database row."""
    if not isinstance(result, dict):
        return
    kind = scan_mode if scan_mode in {"short", "long"} else _horizon(scan_mode or str(result.get("scan_mode") or ""))
    book = str(result.get("book") or "equity")
    key = kind if book == "equity" else f"{book}-{kind}"
    public = _public_result(result)
    public["scan_mode"] = "price" if kind == "long" else public.get("scan_mode") or "crossover"
    public["book"] = book
    try:
        _write_list(key, public)
    except Exception:
        logger.info("crossover list was not stored")
        return
    _remember_cache(key, public)


def latest_crossover_signals() -> list[dict]:
    """Symbols from the saved scans. The browser does not have to still be open."""
    rows = []
    seen = set()
    saved = _stored_lists()
    for result in saved.values():
        if not result:
            continue
        for signal in result.get("signals") or []:
            if not isinstance(signal, dict):
                continue
            symbol = str(signal.get("ticker") or signal.get("symbol") or "").upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            rows.append({
                "symbol": symbol,
                "company_name": signal.get("company") or signal.get("company_name") or symbol,
                "crossover_type": signal.get("crossover_type") or "",
                "exchange": str(signal.get("exchange") or "NSE").upper() or "NSE",
                "instrument_type": str(signal.get("instrument_type") or "EQ").upper() or "EQ",
            })
    return rows


def read_scan(job_id: str) -> Optional[dict]:
    """Return status and, when finished, the scan. Credentials are never included."""
    row = _load(job_id)
    if row is None:
        return None
    result = None
    if row["result_json"]:
        result = json.loads(row["result_json"])
    return {
        "job_id": job_id,
        "status": row["status"],
        "result": result,
        "error": row["error"],
    }


def run_scan_job(job_id: str) -> None:
    """Finish one queued scan using parallel cached scanner (95%+ faster on repeats)."""
    row = _load(job_id)
    if row is None or row["status"] != "running":
        return
    try:
        raw = row["credential_blob"]
        if not raw.startswith("{"):
            raw = _decrypt(raw)
        secret = json.loads(raw)
        kite = KiteConnect(api_key=secret["api_key"])
        kite.set_access_token(secret["access_token"])
        params = json.loads(row["request_json"])
        from kite_app.desk_progress import current_generation

        generation = current_generation()
        
        # Use cached parallel scanner
        scan_all_nse = params.get("scan_all_nse", False)
        budget = 1200 if params.get("full_pass") or scan_all_nse else 180
        
        result = scan_nifty100_parallel_cached(kite, budget_seconds=budget, **params)
        from kite_app.desk_progress import current_generation

        if current_generation() != generation:
            _finish(job_id, "done", None, None)
            return
        result["scan_all_nse"] = bool(scan_all_nse)
        result["full_pass"] = bool(params.get("full_pass"))
        _finish(job_id, "done", json.dumps(result), None)
        save_crossover_list(str(params.get("scan_mode") or result.get("scan_mode") or ""), result)
        if result["full_pass"]:
            save_crossover_list("short", result)
        
        logger.info(
            "Scan completed: %s stocks in %.1fs (cache: %s)",
            result.get("scanned"),
            result.get("elapsed_seconds"),
            result.get("cache", {}),
        )
    except SignalScanError as exc:
        _finish(job_id, "error", None, str(exc))
    except KiteException as exc:
        from kite_app.kite_service import _safe_kite_message

        _finish(job_id, "error", None, _safe_kite_message(exc))
    except Exception:
        logger.exception("Signal scan failed")
        _finish(job_id, "error", None, "The scan could not be completed.")


def _start(job_id: str) -> None:
    function_name = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "").strip()
    if not function_name:
        threading.Thread(target=run_scan_job, args=(job_id,), daemon=True).start()
        return
    try:
        import boto3

        boto3.client("lambda").invoke(
            FunctionName=function_name,
            InvocationType="Event",
            Payload=json.dumps({"source": "kite-scan", "job_id": job_id}).encode("utf-8"),
        )
    except Exception:
        logger.exception("Signal scan could not be queued")
        _finish(job_id, "error", None, "The scan could not be queued.")


def _decrypt(blob: str) -> str:
    from kite_app.session_manager import _decrypt as decrypt_token

    return decrypt_token(blob)


def _use_database() -> bool:
    load_platform_config()
    return bool(os.environ.get("DATABASE_URL", "").strip() and os.environ.get("FERNET_KEY", "").strip())


def _save_new(job_id: str, params: dict, blob: str) -> None:
    payload = {
        "status": "running",
        "request_json": json.dumps(params),
        "credential_blob": blob,
        "result_json": None,
        "error": None,
    }
    if not _use_database():
        _MEMORY[job_id] = payload
        return
    db = get_sessionmaker()()
    try:
        db.add(
            SignalScanJob(
                job_id=job_id,
                created_at=datetime.now(timezone.utc),
                **payload,
            )
        )
        db.commit()
    finally:
        db.close()


def forget_saved_scans() -> None:
    """Drop saved scan coverage so the next read starts at the first name."""
    keys = (
        "short",
        "long",
        "commodity_future-short",
        "commodity_future-long",
        "stock_future-short",
        "stock_future-long",
        "stock_option-short",
        "stock_option-long",
    )
    for key in keys:
        _LISTS.pop(key, None)
    if not _use_database():
        return
    from kite_app.models import SavedCrossoverList

    db = get_sessionmaker()()
    try:
        db.query(SavedCrossoverList).filter(SavedCrossoverList.horizon.in_(keys)).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        logger.info("saved scan coverage was not cleared")
    finally:
        db.close()


def _horizon(scan_mode: str) -> str:
    return "long" if scan_mode == "price" else "short"


def _public_result(result: dict) -> dict:
    public = {key: result.get(key) for key in _PUBLIC_FIELDS}
    signals = public.get("signals") if isinstance(public.get("signals"), list) else []
    public["signals"] = [signal for signal in signals if isinstance(signal, dict)]
    return public


def _cached_list(kind: str) -> Optional[dict]:
    from kite_app.desk_cache import cache_get

    payload = cache_get(f"crossover:{kind}")
    result = payload.get("result") if isinstance(payload, dict) else None
    return result if isinstance(result, dict) else None


def _remember_cache(kind: str, result: dict) -> None:
    from kite_app.desk_cache import cache_set

    cache_set(f"crossover:{kind}", {"result": result})


def _stored_lists() -> dict[str, Optional[dict]]:
    found: dict[str, Optional[dict]] = {}
    if not _use_database():
        for kind, result in _LISTS.items():
            if isinstance(result, dict):
                found[kind] = result
        return found
    from kite_app.models import SavedCrossoverList, get_sessionmaker

    db = get_sessionmaker()()
    try:
        for row in db.query(SavedCrossoverList).all():
            if not row.result_json:
                continue
            try:
                result = json.loads(row.result_json)
            except json.JSONDecodeError:
                continue
            if isinstance(result, dict):
                found[row.horizon] = result
    finally:
        db.close()
    for kind, result in _LISTS.items():
        if kind not in found and isinstance(result, dict):
            found[kind] = result
    return found


def _write_list(kind: str, result: dict) -> None:
    if not _use_database():
        _LISTS[kind] = result
        return
    from kite_app.models import SavedCrossoverList, get_sessionmaker

    db = get_sessionmaker()()
    try:
        row = db.get(SavedCrossoverList, kind)
        payload = json.dumps(result)
        now = datetime.now(timezone.utc)
        if row is None:
            db.add(SavedCrossoverList(horizon=kind, saved_at=now, result_json=payload))
        else:
            row.saved_at = now
            row.result_json = payload
        db.commit()
    finally:
        db.close()


def _done_scans() -> list[dict]:
    """Finished scans, newest first. The credential blob is not copied."""
    if not _use_database():
        rows = []
        for row in reversed(list(_MEMORY.values())):
            if row.get("status") == "done" and row.get("result_json"):
                rows.append({
                    "request_json": row["request_json"],
                    "result_json": row["result_json"],
                })
        return rows
    db = get_sessionmaker()()
    try:
        jobs = (
            db.query(SignalScanJob)
            .filter(SignalScanJob.status == "done", SignalScanJob.result_json.isnot(None))
            .order_by(SignalScanJob.created_at.desc())
            .limit(40)
            .all()
        )
        return [{"request_json": job.request_json, "result_json": job.result_json} for job in jobs]
    finally:
        db.close()


def _load(job_id: str) -> Optional[dict]:
    if not _use_database():
        row = _MEMORY.get(job_id)
        return dict(row) if row else None
    db = get_sessionmaker()()
    try:
        job = db.get(SignalScanJob, job_id)
        if job is None:
            return None
        return {
            "status": job.status,
            "request_json": job.request_json,
            "credential_blob": job.credential_blob,
            "result_json": job.result_json,
            "error": job.error,
        }
    finally:
        db.close()


def _finish(job_id: str, status: str, result_json: Optional[str], error: Optional[str]) -> None:
    if not _use_database():
        row = _MEMORY.get(job_id)
        if row is None:
            return
        row["status"] = status
        row["result_json"] = result_json
        row["error"] = error
        return
    db = get_sessionmaker()()
    try:
        job = db.get(SignalScanJob, job_id)
        if job is None:
            return
        job.status = status
        job.result_json = result_json
        job.error = error
        db.commit()
    finally:
        db.close()
