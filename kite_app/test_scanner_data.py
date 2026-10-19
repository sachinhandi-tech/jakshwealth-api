from datetime import datetime

from kite_app.scanner_data import build_scanner_payload, ohlc_snapshot


class FakeKite:
    def __init__(self) -> None:
        self.calls = 0

    def historical_data(self, token, start, end, interval):
        self.calls += 1
        return [{
            "date": datetime(2026, 10, 1, 0, 0),
            "open": "10",
            "high": 12,
            "low": 9,
            "close": 11,
            "volume": 100,
        }]

    def ohlc(self, symbols):
        return {symbol: {"last_price": "101.5"} for symbol in symbols}


def test_scanner_payload_caches_candles_without_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("SCANNER_CACHE_PATH", str(tmp_path / "scanner-data.json"))
    monkeypatch.setattr("kite_app.scanner_data.load_nifty100", lambda: [
        {"ticker": "INFY", "company": "Infosys"},
        {"ticker": "TCS", "company": "Tata Consultancy"},
    ])
    monkeypatch.setattr("kite_app.scanner_data.nse_equity_tokens", lambda kite: {"INFY": 408065})
    monkeypatch.setattr("kite_app.scanner_data.load_nifty50_symbols", lambda: {"INFY"})
    monkeypatch.setattr("kite_app.scanner_data.time.sleep", lambda _seconds: None)
    kite = FakeKite()

    first = build_scanner_payload(kite, budget_seconds=5)
    second = build_scanner_payload(kite, budget_seconds=5)

    assert kite.calls == 1
    assert first["metadata"]["cached_stocks"] == 1
    assert first["stocks"][0]["symbol"] == "INFY"
    assert first["stocks"][0]["instrument_token"] == 408065
    assert first["stocks"][0]["nifty_flags"] == {"nifty50": True, "nifty100": True}
    assert first["stocks"][0]["candles"][0]["date"] == "2026-10-01"
    assert first["stocks"][0]["candles"][0]["open"] == 10.0
    assert "access_token" not in str(first)
    assert second["stocks"][0]["symbol"] == "INFY"


def test_ohlc_snapshot_uses_last_price():
    payload = ohlc_snapshot(FakeKite(), ["infy", "INFY", ""])
    assert payload == {"quotes": [{"symbol": "INFY", "last_price": 101.5}]}
