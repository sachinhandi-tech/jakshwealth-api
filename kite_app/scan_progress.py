"""Real-time scan progress tracking and performance metrics."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session


class ProgressBase(DeclarativeBase):
    """Scan progress tracking."""


class ScanProgress(ProgressBase):
    """Real-time progress tracking for active scans."""

    __tablename__ = "scan_progress"

    progress_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # running, completed, error
    total_stocks: Mapped[int] = mapped_column(nullable=False)
    processed_stocks: Mapped[int] = mapped_column(default=0)
    signals_found: Mapped[int] = mapped_column(default=0)
    elapsed_seconds: Mapped[float] = mapped_column(default=0.0)
    estimated_total_seconds: Mapped[float] = mapped_column(nullable=True)
    api_calls_made: Mapped[int] = mapped_column(default=0)
    cache_hits: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class ScanPerformance(ProgressBase):
    """Historical scan performance metrics for optimization."""

    __tablename__ = "scan_performance"

    perf_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scan_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    universe_size: Mapped[int] = mapped_column(nullable=False)
    total_time_seconds: Mapped[float] = mapped_column(nullable=False)
    avg_time_per_stock_ms: Mapped[float] = mapped_column(nullable=False)
    signals_found: Mapped[int] = mapped_column(nullable=False)
    api_calls: Mapped[int] = mapped_column(nullable=False)
    cache_hits: Mapped[int] = mapped_column(nullable=False)
    cache_hit_percentage: Mapped[float] = mapped_column(nullable=False)
    workers_used: Mapped[int] = mapped_column(nullable=False)


def update_progress(
    db: Session,
    job_id: str,
    processed: int,
    total: int,
    signals: int,
    elapsed: float,
    api_calls: int,
    cache_hits: int,
) -> None:
    """Update scan progress in real-time."""
    progress = db.query(ScanProgress).filter(
        ScanProgress.job_id == job_id
    ).first()

    if progress:
        progress.processed_stocks = processed
        progress.signals_found = signals
        progress.elapsed_seconds = elapsed
        progress.api_calls_made = api_calls
        progress.cache_hits = cache_hits

        if processed > 0:
            time_per_stock = elapsed / processed
            remaining_stocks = total - processed
            progress.estimated_total_seconds = elapsed + (time_per_stock * remaining_stocks)

        db.commit()


def get_progress(db: Session, job_id: str) -> Optional[dict]:
    """Get real-time progress for a scan."""
    progress = db.query(ScanProgress).filter(
        ScanProgress.job_id == job_id
    ).first()

    if not progress:
        return None

    percentage = (progress.processed_stocks / progress.total_stocks * 100) if progress.total_stocks > 0 else 0

    return {
        "job_id": job_id,
        "status": progress.status,
        "percentage": round(percentage, 1),
        "processed": progress.processed_stocks,
        "total": progress.total_stocks,
        "signals_found": progress.signals_found,
        "elapsed_seconds": round(progress.elapsed_seconds, 1),
        "estimated_total_seconds": round(progress.estimated_total_seconds, 1) if progress.estimated_total_seconds else None,
        "api_calls": progress.api_calls_made,
        "cache_hits": progress.cache_hits,
        "time_per_stock_ms": round((progress.elapsed_seconds / progress.processed_stocks * 1000), 2) if progress.processed_stocks > 0 else 0,
    }


def get_performance_metrics(db: Session, limit: int = 10) -> list[dict]:
    """Get last N scan performance metrics."""
    metrics = db.query(ScanPerformance).order_by(
        ScanPerformance.scan_date.desc()
    ).limit(limit).all()

    return [
        {
            "scan_date": m.scan_date.isoformat(),
            "universe_size": m.universe_size,
            "total_time_seconds": round(m.total_time_seconds, 1),
            "avg_time_per_stock_ms": round(m.avg_time_per_stock_ms, 2),
            "signals_found": m.signals_found,
            "api_calls": m.api_calls,
            "cache_hits": m.cache_hits,
            "cache_hit_percentage": round(m.cache_hit_percentage, 1),
            "workers": m.workers_used,
        }
        for m in metrics
    ]
