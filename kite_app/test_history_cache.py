from datetime import date

from kite_app.signals_cache import get_cached_candles, history_by_ticker


def test_history_reads_redis_before_postgres(monkeypatch):
    def cache_get(key):
        if key != "history:INFY":
            return None
        return {
            "start": "2026-01-01",
            "end": "2026-06-01",
            "candles": [{"date": "2026-06-01", "open": 9, "high": 11, "low": 8, "close": 10, "volume": 100}],
        }

    monkeypatch.setattr("kite_app.desk_cache.cache_get", cache_get)
    monkeypatch.setattr("kite_app.models.get_sessionmaker", lambda: (_ for _ in ()).throw(AssertionError("db")))

    rows = history_by_ticker(["infy"])

    assert rows[0]["symbol"] == "INFY"
    assert rows[0]["candles"][0]["close"] == 10


def test_candle_read_uses_redis_before_postgres(monkeypatch):
    monkeypatch.setattr("kite_app.desk_cache.cache_get", lambda key: {
        "start": "2026-01-01",
        "end": "2026-06-01",
        "candles": [{"date": "2026-06-01", "close": 10}],
    })

    class Boom:
        def query(self, *_args, **_kwargs):
            raise AssertionError("db")

    candles = get_cached_candles(Boom(), 1, "INFY", date(2026, 2, 1), date(2026, 5, 1))

    assert candles[0]["close"] == 10


def test_saved_bars_skip_zerodha_when_they_match_the_published_day(monkeypatch):
    from kite_app.signals_cache import get_candles_with_cache

    monkeypatch.setattr("kite_app.signals_cache._wait_for_kite", lambda: (_ for _ in ()).throw(AssertionError("kite")))
    saved = [
        {"date": "2026-01-01", "close": 10},
        {"date": "2026-10-23", "close": 12},
    ]

    found = get_candles_with_cache(
        object(),
        object(),
        1,
        "INFY",
        date(2026, 1, 1),
        date(2026, 10, 24),
        fresh_through=date(2026, 10, 23),
        known=saved,
    )

    assert found[-1]["close"] == 12


def test_only_the_missing_days_are_fetched(monkeypatch):
    from kite_app.signals_cache import get_candles_with_cache

    calls = []

    class Kite:
        def historical_data(self, instrument_token, from_date, to_date, interval):
            calls.append(from_date)
            return [{"date": "2026-10-23", "close": 13, "volume": 10}]

    monkeypatch.setattr("kite_app.signals_cache._wait_for_kite", lambda: None)
    monkeypatch.setattr("kite_app.signals_cache.cache_candles", lambda *args, **kwargs: None)
    saved = [
        {"date": "2026-01-01", "close": 10},
        {"date": "2026-10-22", "close": 12},
    ]

    found = get_candles_with_cache(
        Kite(),
        object(),
        1,
        "INFY",
        date(2026, 1, 1),
        date(2026, 10, 24),
        fresh_through=date(2026, 10, 23),
        known=saved,
    )

    assert calls == [date(2026, 10, 23)]
    assert [row["close"] for row in found] == [10, 12, 13]
