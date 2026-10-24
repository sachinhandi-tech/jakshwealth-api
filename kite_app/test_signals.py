import time
from datetime import date, timedelta

from kite_app.signals import (
    exponential_moving_average,
    latest_crossover,
    latest_price_cross,
    parse_nifty100_csv,
    scan_nifty100,
    simple_moving_average,
    weighted_moving_average,
)


def test_simple_moving_average():
    averages = simple_moving_average([1, 2, 3, 4, 5], 3)
    assert averages[:2] == [None, None]
    assert averages[2:] == [2, 3, 4]


def test_exponential_moving_average_uses_the_standard_smoothing_factor():
    averages = exponential_moving_average([1, 2, 3, 4, 5], 3)
    assert averages[:2] == [None, None]
    assert averages[2:] == [2, 3, 4]


def test_weighted_moving_average_weights_the_newest_close_highest():
    averages = weighted_moving_average([1, 2, 3, 4, 5], 3)
    assert averages[:2] == [None, None]
    assert averages[2] == 14 / 6
    assert averages[3] == 20 / 6
    assert averages[4] == 26 / 6


def test_latest_crossover_accepts_ema_and_wma():
    start = date(2026, 3, 1)
    flat = [{"date": start + timedelta(days=index), "close": 10} for index in range(8)]
    rising = [{"date": start + timedelta(days=8 + index), "close": 14 + index * 3} for index in range(5)]
    candles = flat + rising
    for ma_type in ("ema", "wma"):
        found = latest_crossover(candles, short_window=2, long_window=4, lookback_days=10, ma_type=ma_type)
        assert found is not None
        assert found["crossover_type"] == "bullish"


def test_short_term_can_cross_an_ema_through_an_sma_and_keep_the_200_trend():
    start = date(2026, 4, 1)
    flat = [{"date": start + timedelta(days=index), "close": 10} for index in range(8)]
    rising = [{"date": start + timedelta(days=8 + index), "close": 14 + index * 3} for index in range(6)]
    found = latest_crossover(
        flat + rising,
        short_window=2,
        long_window=4,
        lookback_days=10,
        short_type="ema",
        long_type="sma",
        trend_window=3,
    )
    assert found is not None
    assert found["crossover_type"] == "bullish"
    assert found["trend_sma"] is not None
    assert found["trend_bias"] == "above"


def test_long_term_price_crosses_through_the_sma():
    start = date(2026, 5, 1)
    flat = [{"date": start + timedelta(days=index), "close": 10} for index in range(6)]
    rising = [{"date": start + timedelta(days=6 + index), "close": 16 + index} for index in range(3)]
    found = latest_price_cross(flat + rising, window=4, lookback_days=8)
    assert found is not None
    assert found["crossover_type"] == "bullish"
    assert found["trend_bias"] == "above"


def test_latest_crossover_keeps_the_newest_cross_inside_lookback():
    start = date(2026, 1, 1)
    flat = [{"date": start + timedelta(days=index), "close": 10} for index in range(6)]
    rising = [{"date": start + timedelta(days=6 + index), "close": 12 + index * 2} for index in range(4)]
    candles = flat + rising

    found = latest_crossover(candles, short_window=2, long_window=4, lookback_days=8)

    assert found is not None
    assert found["crossover_type"] == "bullish"
    assert found["crossover_date"] == candles[-1]["date"].isoformat() or found["short_sma"] > found["long_sma"]


def test_parallel_scan_keeps_a_real_cross_and_explains_it(monkeypatch):
    from datetime import date, timedelta

    from kite_app.signals_parallel_cached import scan_nifty100_parallel_cached

    start = date(2024, 1, 1)
    flat = [{"date": start + timedelta(days=index), "close": 10} for index in range(40)]
    rising = [{"date": start + timedelta(days=40 + index), "close": 14 + index} for index in range(12)]
    quiet = [{"date": start + timedelta(days=index), "close": 10} for index in range(8)]

    class Database:
        def close(self):
            return None

    def candles(kite, db, token, ticker, start_date, end_date):
        assert (end_date - start_date).days > 20
        if ticker == "QUIET":
            return quiet
        return flat + rising

    monkeypatch.setattr(
        "kite_app.signals_parallel_cached.get_sessionmaker",
        lambda: (lambda: Database()),
    )
    monkeypatch.setattr("kite_app.signals_parallel_cached.get_candles_with_cache", candles)
    monkeypatch.setattr(
        "kite_app.signals_parallel_cached.load_nifty100",
        lambda: [
            {"ticker": "RISE", "company": "Rising Ltd"},
            {"ticker": "QUIET", "company": "Quiet Ltd"},
        ],
    )
    monkeypatch.setattr(
        "kite_app.signals_parallel_cached.nse_equity_tokens",
        lambda kite: {"RISE": 1, "QUIET": 2},
    )

    result = scan_nifty100_parallel_cached(
        kite=object(),
        scan_mode="crossover",
        short_type="ema",
        long_type="sma",
        short_window=3,
        long_window=8,
        trend_window=5,
        lookback_days=30,
        max_stocks=10,
        budget_seconds=5,
    )

    assert result["scanned"] == 2
    assert result["skipped"] == 1
    assert [row["ticker"] for row in result["signals"]] == ["RISE"]
    assert result["signals"][0]["crossover_type"] == "bullish"
    assert "crossed above" in result["signals"][0]["reason"]
    assert "5 SMA" in result["signals"][0]["reason"]


def test_bearish_crossover():
    start = date(2026, 2, 1)
    high = [{"date": start + timedelta(days=index), "close": 20} for index in range(6)]
    falling = [{"date": start + timedelta(days=6 + index), "close": 16 - index * 3} for index in range(4)]
    found = latest_crossover(high + falling, short_window=2, long_window=4, lookback_days=10)
    assert found is not None
    assert found["crossover_type"] == "bearish"


def test_parse_nifty100_csv_reads_symbol_and_company():
    text = "\n".join(
        [
            "Company Name,Industry,Symbol,Series,ISIN Code",
            *[f"Company {index},Sector,SYM{index},EQ,INE{index:06d}" for index in range(60)],
        ]
    )
    rows = parse_nifty100_csv(text)
    assert rows[0] == {"ticker": "SYM0", "company": "Company 0"}
    assert len(rows) == 60


def test_scan_job_result_omits_the_access_token(monkeypatch):
    from kite_app.scan_jobs import enqueue_scan, read_scan, run_scan_job

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("FERNET_KEY", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setattr("kite_app.scan_jobs._start", lambda job_id: None)
    monkeypatch.setattr(
        "kite_app.scan_jobs.scan_nifty100_parallel_cached",
        lambda kite, **kwargs: {"signals": [], "scanned": 1, "universe": 1, "skipped": 0},
    )
    job_id = enqueue_scan(
        {"api_key": "key", "access_token": "secret-token"},
        {
            "short_window": 2,
            "long_window": 4,
            "lookback_days": 5,
            "max_stocks": 10,
            "ma_type": "sma",
            "short_type": "sma",
            "long_type": "sma",
            "trend_window": 0,
            "scan_mode": "crossover",
        },
    )
    run_scan_job(job_id)
    body = read_scan(job_id)
    assert body is not None
    assert body["status"] == "done"
    assert "secret-token" not in str(body)


def test_saved_crossover_scans_are_read_without_the_open_browser(monkeypatch):
    import json
    from kite_app import scan_jobs

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("FERNET_KEY", raising=False)
    scan_jobs._MEMORY.clear()
    scan_jobs._LISTS.clear()
    try:
        scan_jobs._save_new("old-short", {"scan_mode": "crossover"}, "secret-token")
        scan_jobs._finish("old-short", "done", json.dumps({
            "scan_mode": "crossover",
            "signals": [{"ticker": "OLD", "company": "Old Ltd", "crossover_type": "bullish"}],
        }), None)
        scan_jobs._save_new("new-short", {"scan_mode": "crossover"}, "secret-token")
        scan_jobs._finish("new-short", "done", json.dumps({
            "scan_mode": "crossover",
            "signals": [{"ticker": "INFY", "company": "Infosys", "crossover_type": "bullish"}],
        }), None)
        scan_jobs._save_new("long", {"scan_mode": "price"}, "secret-token")
        scan_jobs._finish("long", "done", json.dumps({
            "scan_mode": "price",
            "signals": [{"ticker": "TCS", "company": "TCS Ltd", "crossover_type": "bearish"}],
        }), None)
        saved = scan_jobs.latest_crossover_scans()
        signals = scan_jobs.latest_crossover_signals()
    finally:
        scan_jobs._MEMORY.clear()
        scan_jobs._LISTS.clear()
    assert [row["ticker"] for row in saved["short"]["signals"]] == ["INFY"]
    assert [row["ticker"] for row in saved["long"]["signals"]] == ["TCS"]
    assert {row["symbol"]: row["crossover_type"] for row in signals} == {"INFY": "bullish", "TCS": "bearish"}
    assert "secret-token" not in str(saved)


def test_final_call_reads_the_saved_list_from_redis_before_the_jobs(monkeypatch):
    from kite_app import scan_jobs

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("FERNET_KEY", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    scan_jobs._MEMORY.clear()
    scan_jobs._LISTS.clear()
    store = {}

    def cache_get(key):
        return store.get(key)

    def cache_set(key, value, ttl=21600):
        store[key] = value

    monkeypatch.setattr("kite_app.desk_cache.cache_get", cache_get)
    monkeypatch.setattr("kite_app.desk_cache.cache_set", cache_set)
    try:
        scan_jobs.save_crossover_list("crossover", {
            "scan_mode": "crossover",
            "signals": [{"ticker": "INFY", "company": "Infosys", "crossover_type": "bullish"}],
        })
        scan_jobs._LISTS.clear()
        scan_jobs._MEMORY["noise"] = {
            "status": "done",
            "request_json": "{\"scan_mode\": \"crossover\"}",
            "result_json": "{\"signals\": [{\"ticker\": \"NOISE\", \"crossover_type\": \"bearish\"}]}",
        }
        saved = scan_jobs.latest_crossover_scans()
    finally:
        scan_jobs._MEMORY.clear()
        scan_jobs._LISTS.clear()
    assert saved["short"]["signals"][0]["ticker"] == "INFY"
    assert "crossover:short" in store


def test_finished_commodity_pass_is_kept(monkeypatch):
    import json

    from kite_app import scan_jobs
    from kite_app.desk_progress import clear_activity, resume_scan

    monkeypatch.setattr(scan_jobs, "_use_database", lambda: False)
    clear_activity()
    scan_jobs._MEMORY.clear()
    scan_jobs._LISTS.clear()
    started = []
    monkeypatch.setattr(scan_jobs, "enqueue_scan", lambda record, params: started.append(params["book"]) or "job")
    resume_scan()
    try:
        scan_jobs._MEMORY["mcx"] = {
            "status": "done",
            "request_json": json.dumps({
                "scan_all_nse": True,
                "book": "commodity_future",
                "scan_mode": "price",
            }),
            "result_json": json.dumps({
                "book": "commodity_future",
                "scan_all_nse": True,
                "universe": 31,
                "scanned": 31,
                "skipped": 0,
                "signals": [],
            }),
        }
        covered = {
            "book": "equity",
            "scan_all_nse": True,
            "universe": 2500,
            "scanned": 2500,
            "skipped": 0,
        }
        scan_jobs._LISTS["short"] = dict(covered)
        scan_jobs._LISTS["long"] = dict(covered)
        assert scan_jobs._book_covered("commodity_future") is True
        assert "mcx-short" in scan_jobs._LISTS
        assert "mcx-long" in scan_jobs._LISTS
        assert "commodity_future-short" not in scan_jobs._LISTS
        assert all(len(key) <= 16 for key in scan_jobs._LISTS)
        scan_jobs._MEMORY["again"] = {
            "status": "running",
            "request_json": json.dumps({"scan_all_nse": True, "book": "commodity_future"}),
            "result_json": None,
            "error": None,
        }
        scan_jobs.ensure_listed_equity_scan({"api_key": "k", "access_token": "t"})
        assert started == []
        assert "commodity_future" not in started
    finally:
        scan_jobs._MEMORY.clear()
        scan_jobs._LISTS.clear()


def test_scan_returns_before_the_gateway_timeout(monkeypatch):
    import kite_app.signals as signals

    monkeypatch.setattr(signals, "SCAN_BUDGET_SECONDS", 0.45)
    monkeypatch.setattr(
        signals,
        "load_nifty100",
        lambda: [{"ticker": f"S{index}", "company": "Company"} for index in range(40)],
    )
    monkeypatch.setattr(signals, "nse_equity_tokens", lambda kite: {f"S{index}": index for index in range(40)})

    class SlowKite:
        def historical_data(self, *args, **kwargs):
            time.sleep(0.05)
            return []

    started = time.monotonic()
    result = scan_nifty100(SlowKite(), 5, 10, 5, 10)
    assert time.monotonic() - started < 2
    assert 0 < result["scanned"] < 40
    assert result["universe"] == 40
