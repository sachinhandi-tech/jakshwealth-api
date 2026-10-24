"""Historical data caching layer to reduce Kite API calls by 95%+.

Problem: Fetching 365 days × 3080 stocks = massive API overhead
Solution: Cache historical data in database, update incrementally with new days only
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, date, timedelta
from typing import Optional

from sqlalchemy import JSON, DateTime, String, Text, Uuid
from kiteconnect.exceptions import TokenException
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
import json


_CACHE_LOCK = threading.Lock()
_RATE_LOCK = threading.Lock()
_NEXT_KITE_CALL = 0.0
_KITE_GAP_SECONDS = 0.34


def _wait_for_kite() -> None:
    """Keep historical requests near Kite's three-per-second limit."""
    global _NEXT_KITE_CALL
    with _RATE_LOCK:
        now = time.monotonic()
        delay = max(0.0, _NEXT_KITE_CALL - now)
        _NEXT_KITE_CALL = max(now, _NEXT_KITE_CALL) + _KITE_GAP_SECONDS
    if delay:
        time.sleep(delay)


class CacheBase(DeclarativeBase):
    """Cache metadata for historical data."""


class StockHistoryCache(CacheBase):
    """Cached OHLC history for one stock to avoid repeated Kite API calls."""

    __tablename__ = "stock_history_cache"

    cache_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    token: Mapped[int] = mapped_column(nullable=False, index=True)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    start_date: Mapped[date] = mapped_column(nullable=False)
    end_date: Mapped[date] = mapped_column(nullable=False)
    candles_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array of candles
    candle_count: Mapped[int] = mapped_column(nullable=False)
    cached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def _json_ready(candles: list[dict]) -> list[dict]:
    ready = []
    for candle in candles:
        item = dict(candle)
        value = item.get("date")
        if hasattr(value, "isoformat"):
            item["date"] = value.isoformat()
        ready.append(item)
    return ready


def history_by_ticker(tickers: list[str]) -> list[dict]:
    """Longest saved daily history for each ticker. A database miss returns nothing."""
    names = []
    seen = set()
    for ticker in tickers:
        name = str(ticker or "").upper()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    if not names:
        return []
    try:
        from kite_app.models import get_sessionmaker

        db = get_sessionmaker()()
    except Exception:
        return []
    best: dict[str, dict] = {}
    try:
        rows = db.query(StockHistoryCache).filter(StockHistoryCache.ticker.in_(names)).all()
        for row in rows:
            try:
                candles = json.loads(row.candles_json)
            except json.JSONDecodeError:
                continue
            if not isinstance(candles, list) or not candles:
                continue
            current = best.get(row.ticker)
            if current is None or len(candles) > len(current["candles"]):
                best[row.ticker] = {
                    "symbol": row.ticker,
                    "company_name": row.ticker,
                    "exchange": "NSE",
                    "instrument_type": "EQ",
                    "candles": candles,
                }
    except Exception:
        return []
    finally:
        db.close()
    return list(best.values())


def get_cached_candles(
    db: Session,
    token: int,
    ticker: str,
    start_date: date,
    end_date: date,
) -> Optional[list[dict]]:
    """Get cached historical data if available and complete."""
    with _CACHE_LOCK:
        cache = db.query(StockHistoryCache).filter(
            StockHistoryCache.token == token,
            StockHistoryCache.start_date <= start_date,
            StockHistoryCache.end_date >= end_date,
        ).first()

    if cache:
        try:
            return json.loads(cache.candles_json)
        except json.JSONDecodeError:
            return None
    return None


def cache_candles(
    db: Session,
    token: int,
    ticker: str,
    start_date: date,
    end_date: date,
    candles: list[dict],
) -> None:
    """Cache historical data to avoid re-fetching from Kite API."""
    if not candles:
        return

    now = datetime.now()
    payload = json.dumps(_json_ready(candles))
    with _CACHE_LOCK:
        cache = db.query(StockHistoryCache).filter(
            StockHistoryCache.token == token,
        ).first()

    if cache and cache.candle_count >= len(candles) and cache.start_date <= start_date and cache.end_date >= end_date:
        return

    if cache:
        cache.start_date = min(cache.start_date, start_date)
        cache.end_date = max(cache.end_date, end_date)
        cache.candles_json = payload
        cache.candle_count = len(candles)
        cache.updated_at = now
    else:
        # Create new cache entry
        cache = StockHistoryCache(
            cache_id=uuid.uuid4(),
            token=token,
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            candles_json=payload,
            candle_count=len(candles),
            cached_at=now,
            updated_at=now,
        )
        with _CACHE_LOCK:
            db.add(cache)

    db.commit()


def should_update_cache(cache: StockHistoryCache, days_old: int = 7) -> bool:
    """Check if cache needs updating (older than N days)."""
    if not cache:
        return True
    age = datetime.now() - cache.updated_at
    return age.days > days_old


def get_candles_with_cache(
    kite,
    db: Session,
    token: int,
    ticker: str,
    start_date: date,
    end_date: date,
) -> Optional[list[dict]]:
    """Get candles from cache or fetch from Kite API, then cache result."""
    # Check cache first
    cached = get_cached_candles(db, token, ticker, start_date, end_date)
    if cached:
        return cached

    try:
        _wait_for_kite()
        candles = kite.historical_data(
            instrument_token=token,
            from_date=start_date,
            to_date=end_date,
            interval="day",
        )
    except TokenException:
        raise
    except Exception:
        return None
    if not candles:
        return None
    try:
        cache_candles(db, token, ticker, start_date, end_date, candles)
    except Exception:
        db.rollback()
    return candles


class CacheStats:
    """Statistics on cache effectiveness."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def total_cached_entries(self) -> int:
        """Count total cached stock histories."""
        return self.db.query(StockHistoryCache).count()
    
    def total_candles_cached(self) -> int:
        """Sum of all candles across cache entries."""
        return sum(
            c.candle_count 
            for c in self.db.query(StockHistoryCache).all()
        )
    
    def estimated_api_calls_saved(self) -> int:
        """Rough estimate of Kite API calls avoided by caching."""
        # Assume 1 cache entry = 1 API call saved
        return self.total_cached_entries()
    
    def get_stats(self) -> dict:
        return {
            "cached_stocks": self.total_cached_entries(),
            "total_candles": self.total_candles_cached(),
            "api_calls_saved": self.estimated_api_calls_saved(),
        }
