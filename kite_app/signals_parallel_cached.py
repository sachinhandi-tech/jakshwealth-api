"""Parallel MA crossover scan. Cached history, paced Kite calls, real crosses only."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Optional

from kiteconnect.exceptions import KiteException, TokenException

from kite_app.models import get_sessionmaker
from kite_app.signals import (
    SignalScanError,
    explain_signal,
    history_span_days,
    latest_crossover,
    latest_price_cross,
    load_nifty100,
    nse_equity_tokens,
)
from kite_app.signals_cache import get_candles_with_cache

logger = logging.getLogger("kite_app.scan")

MAX_WORKERS = 6
SCAN_BUDGET_SECONDS = 22
SCAN_BUDGET_SECONDS_ASYNC = 180


def _signal_row(ticker: str, company: str, exchange: str, found: dict, scan_mode: str, short_window: int, long_window: int, short_type: str, long_type: str, trend_window: int) -> dict:
    reason = explain_signal(
        found,
        scan_mode=scan_mode,
        short_window=short_window,
        long_window=long_window,
        short_type=short_type,
        long_type=long_type,
        trend_window=trend_window,
    )
    return {
        "ticker": ticker,
        "company": company or ticker,
        "exchange": str(exchange or "NSE").upper() or "NSE",
        "reason": reason,
        **found,
    }


def _scan_stock_cached(
    kite,
    ticker: str,
    token: int,
    company: str,
    lookback_days: int,
    short_window: int,
    long_window: int,
    trend_window: int,
    short_type: str,
    long_type: str,
    scan_mode: str,
    exchange: str = "NSE",
    full_pass: bool = False,
) -> tuple[Optional[object], str]:
    """Return a real crossover, or a status of none or skipped."""
    db_session = get_sessionmaker()()
    try:
        end_date = date.today()
        start_date = end_date - timedelta(
            days=history_span_days(lookback_days, long_window, trend_window)
        )
        candles = get_candles_with_cache(
            kite,
            db_session,
            token,
            ticker,
            start_date,
            end_date,
        )
        needed = long_window + 1
        if not candles or len(candles) < needed:
            return None, "skipped"
        if full_pass:
            found_rows = []
            crossed = latest_crossover(
                candles,
                short_window,
                50,
                60,
                short_type,
                short_type,
                "sma",
                trend_window,
            )
            if crossed is not None:
                found_rows.append(_signal_row(ticker, company, exchange, crossed, "crossover", short_window, 50, short_type, "sma", trend_window))
            priced = latest_price_cross(candles, trend_window, lookback_days)
            if priced is not None:
                found_rows.append(_signal_row(ticker, company, exchange, priced, "price", short_window, trend_window, "sma", "sma", trend_window))
            if not found_rows:
                return None, "none"
            return found_rows, "signal"
        if scan_mode == "price":
            found = latest_price_cross(candles, long_window, lookback_days)
        else:
            found = latest_crossover(
                candles,
                short_window,
                long_window,
                lookback_days,
                short_type,
                short_type,
                long_type,
                trend_window,
            )
        if found is None:
            return None, "none"
        reason = explain_signal(
            found,
            scan_mode=scan_mode,
            short_window=short_window,
            long_window=long_window,
            short_type=short_type,
            long_type=long_type,
            trend_window=trend_window,
        )
        return {
            "ticker": ticker,
            "company": company or ticker,
            "exchange": str(exchange or "NSE").upper() or "NSE",
            "reason": reason,
            **found,
        }, "signal"
    except TokenException:
        raise
    except Exception as exc:
        logger.info("stock scan skipped %s %s", ticker, exc.__class__.__name__)
        return None, "skipped"
    finally:
        db_session.close()


def scan_nifty100_parallel_cached(
    kite,
    scan_mode: str = "crossover",
    ma_type: str = "ema",
    short_type: str = "ema",
    long_type: str = "sma",
    short_window: int = 20,
    long_window: int = 50,
    trend_window: int = 200,
    lookback_days: int = 60,
    max_stocks: int = 100,
    scan_all_nse: bool = False,
    budget_seconds: Optional[float] = None,
    book: str = "equity",
    full_pass: bool = False,
) -> dict:
    """Scan the chosen universe and keep only crosses inside the lookback."""
    start_time = time.monotonic()
    deadline = start_time + (SCAN_BUDGET_SECONDS if budget_seconds is None else budget_seconds)
    universe_count = 0
    scanned = 0
    signals: list[dict] = []
    progress_key = f"{book}:{scan_mode}" if scan_all_nse else scan_mode

    db = get_sessionmaker()()
    try:
        if scan_all_nse:
            from kite_app.scanner_data import trade_universe

            wanted = book or "equity"
            constituents = [row for row in trade_universe(kite) if row.get("book") == wanted]
        else:
            tokens = nse_equity_tokens(kite)
            constituents = [
                {**row, "token": tokens.get(row["ticker"])}
                for row in load_nifty100()
            ]

        if not constituents:
            if scan_all_nse:
                return {
                    "scan_mode": str(scan_mode),
                    "book": book or "equity",
                    "universe": 0,
                    "scanned": 0,
                    "skipped": 0,
                    "signals": [],
                    "empty_book": True,
                    "scan_all_nse": True,
                }
            raise SignalScanError("Could not load stock universe")

        constituents = constituents[:max_stocks]
        universe_count = len(constituents)
        skipped = 0
        queued = []
        for constituent in constituents:
            token = constituent.get("token")
            if token is None:
                skipped += 1
                continue
            queued.append(constituent)

        if not queued:
            raise SignalScanError("No valid tokens found")

        signals = []
        scanned = 0
        from kite_app.desk_progress import note_scan

        note_scan(progress_key, 0, universe_count, 0, True)
        from kite_app.desk_progress import scan_paused

        executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
        futures = {}
        try:
            for constituent in queued:
                if time.monotonic() > deadline or scan_paused():
                    break
                future = executor.submit(
                    _scan_stock_cached,
                    kite,
                    constituent["ticker"],
                    constituent["token"],
                    constituent.get("company") or constituent["ticker"],
                    lookback_days,
                    short_window,
                    long_window,
                    trend_window,
                    short_type,
                    long_type,
                    scan_mode,
                    str(constituent.get("exchange") or "NSE"),
                    full_pass,
                )
                futures[future] = constituent["ticker"]

            for future in as_completed(list(futures)):
                if time.monotonic() > deadline or scan_paused():
                    break
                found, status = future.result()
                scanned += 1
                rows = found if isinstance(found, list) else ([found] if found else [])
                if status == "skipped":
                    skipped += 1
                for item in rows:
                    if not isinstance(item, dict):
                        continue
                    source = next((row for row in queued if row["ticker"] == futures[future]), {})
                    item["instrument_type"] = source.get("instrument_type") or "EQ"
                    item["book"] = source.get("book") or book or "equity"
                    signals.append(item)
                note_scan(progress_key, scanned, universe_count, len(signals), True)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        signals.sort(key=lambda row: (row["crossover_date"], row["ticker"]), reverse=True)
        for rank, signal in enumerate(signals, start=1):
            signal["rank"] = rank

        elapsed = time.monotonic() - start_time
        try:
            from kite_app.signals_cache import CacheStats

            cache_info = CacheStats(db).get_stats()
        except Exception:
            cache_info = {"cached_stocks": 0, "total_candles": 0, "api_calls_saved": 0}

        return {
            "scan_mode": str(scan_mode),
            "ma_type": str(ma_type),
            "short_type": str(short_type),
            "long_type": str(long_type),
            "short_window": int(short_window),
            "long_window": int(long_window),
            "trend_window": int(trend_window),
            "lookback_days": int(lookback_days),
            "universe": int(universe_count),
            "scanned": int(scanned),
            "skipped": int(skipped),
            "signals": signals,
            "elapsed_seconds": round(float(elapsed), 2),
            "workers": int(MAX_WORKERS),
            "cache": cache_info,
            "book": book or "equity",
        }
    except SignalScanError:
        raise
    except (KiteException, TokenException):
        raise
    except Exception as exc:
        raise SignalScanError("The scan could not be completed.") from exc
    finally:
        try:
            from kite_app.desk_progress import note_scan

            note_scan(progress_key, scanned, universe_count, len(signals), False)
        except Exception:
            pass
        db.close()
