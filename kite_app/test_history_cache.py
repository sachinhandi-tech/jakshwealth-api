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
