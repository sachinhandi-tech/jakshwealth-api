import json
from datetime import datetime

from kite_app.breakout_scan import self_test_fixture
from kite_app.scanner_data import build_scanner_payload, equity_universe, ohlc_snapshot


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


def test_equity_universe_keeps_regular_shares_only(monkeypatch):
    class Instruments:
        def instruments(self, exchange):
            if exchange == "BSE":
                return [
                    {"exchange": "BSE", "segment": "BSE", "instrument_type": "EQ", "tradingsymbol": "INFY", "name": "Infosys", "instrument_token": 11},
                    {"exchange": "BSE", "segment": "BSE", "instrument_type": "EQ", "tradingsymbol": "BSEONLY", "name": "Bse Only", "instrument_token": 12},
                ]
            if exchange != "NSE":
                return []
            return [
                {"exchange": "NSE", "segment": "NSE", "instrument_type": "EQ", "tradingsymbol": "TCS", "name": "Tata", "instrument_token": 2},
                {"exchange": "NSE", "segment": "NSE", "instrument_type": "EQ", "tradingsymbol": "INFY", "name": "Infosys", "instrument_token": 1},
                {"exchange": "NSE", "segment": "NSE", "instrument_type": "EQ", "tradingsymbol": "BAJAJ-AUTO", "name": "Bajaj Auto", "instrument_token": 3},
                {"exchange": "NSE", "segment": "NSE", "instrument_type": "EQ", "tradingsymbol": "RELIANCE-BE", "name": "Reliance", "instrument_token": 4},
                {"exchange": "NSE", "segment": "NSE", "instrument_type": "EQ", "tradingsymbol": "ACME-SM", "name": "Acme SME", "instrument_token": 5},
                {"exchange": "NSE", "segment": "NSE", "instrument_type": "EQ", "tradingsymbol": "BOND-GS", "name": "Govt bond", "instrument_token": 6},
                {"exchange": "NSE", "segment": "NSE", "instrument_type": "EQ", "tradingsymbol": "NIFTYBEES", "name": "Nippon India ETF", "instrument_token": 7},
                {"exchange": "NSE", "segment": "NSE", "instrument_type": "FUT", "tradingsymbol": "INFY24OCTFUT", "name": "INFY", "instrument_token": 9},
                {"exchange": "NSE", "segment": "INDICES", "instrument_type": "EQ", "tradingsymbol": "NIFTY 50", "name": "NIFTY", "instrument_token": 8},
            ]

    monkeypatch.setattr("kite_app.scanner_data._universe_cache", None)
    monkeypatch.setattr(
        "kite_app.scanner_data.listed_cap_symbols",
        lambda: {"BAJAJ-AUTO", "INFY", "RELIANCE-BE", "TCS"},
    )
    rows = equity_universe(Instruments())

    assert [row["ticker"] for row in rows] == ["BAJAJ-AUTO", "INFY", "RELIANCE-BE", "TCS"]
    assert next(row for row in rows if row["ticker"] == "INFY")["exchange"] == "NSE"
    assert next(row for row in rows if row["ticker"] == "INFY")["token"] == 1


def test_trade_universe_splits_shares_futures_options_and_commodities(monkeypatch):
    from datetime import date

    near = date(2026, 11, 26)
    far = date(2026, 12, 31)

    class Instruments:
        def instruments(self, exchange):
            if exchange == "NSE":
                return [
                    {"exchange": "NSE", "segment": "NSE", "instrument_type": "EQ", "tradingsymbol": "RELIANCE", "name": "Reliance", "instrument_token": 1},
                    {"exchange": "NSE", "segment": "NSE", "instrument_type": "EQ", "tradingsymbol": "500325", "name": "Numeric junk", "instrument_token": 2},
                ]
            if exchange == "BSE":
                return [
                    {"exchange": "BSE", "segment": "BSE", "instrument_type": "EQ", "tradingsymbol": "PREFCO", "name": "Prefco Preference", "instrument_token": 3},
                ]
            if exchange == "NFO":
                return [
                    {"exchange": "NFO", "instrument_type": "FUT", "tradingsymbol": "NIFTY26NOVFUT", "name": "NIFTY", "instrument_token": 4, "expiry": near},
                    {"exchange": "NFO", "instrument_type": "FUT", "tradingsymbol": "RELIANCE26NOVFUT", "name": "RELIANCE", "instrument_token": 5, "expiry": near},
                    {"exchange": "NFO", "instrument_type": "CE", "tradingsymbol": "RELIANCE26NOV1500CE", "name": "RELIANCE", "instrument_token": 6, "expiry": near},
                    {"exchange": "NFO", "instrument_type": "CE", "tradingsymbol": "RELIANCE26DEC1500CE", "name": "RELIANCE", "instrument_token": 7, "expiry": far},
                    {"exchange": "NFO", "instrument_type": "PE", "tradingsymbol": "RELIANCE26NOV1500PE", "name": "RELIANCE", "instrument_token": 8, "expiry": near},
                ]
            if exchange == "MCX":
                return [
                    {"exchange": "MCX", "instrument_type": "FUT", "tradingsymbol": "GOLD26NOVFUT", "name": "GOLD", "instrument_token": 9, "expiry": near},
                    {"exchange": "MCX", "instrument_type": "CE", "tradingsymbol": "GOLD26NOVCE", "name": "GOLD", "instrument_token": 10, "expiry": near},
                ]
            return []

    monkeypatch.setattr("kite_app.scanner_data._universe_cache", None)
    monkeypatch.setattr("kite_app.scanner_data.listed_cap_symbols", lambda: {"RELIANCE", "GOLD"})
    from kite_app.scanner_data import trade_universe

    rows = trade_universe(Instruments())
    by_book: dict[str, list[str]] = {}
    for row in rows:
        by_book.setdefault(row["book"], []).append(row["ticker"])

    assert by_book["equity"] == ["RELIANCE"]
    assert "stock_future" not in by_book
    assert "stock_option" not in by_book
    assert "commodity_future" not in by_book


def test_scanner_payload_caches_candles_without_secrets(monkeypatch, tmp_path):
    cache_file = tmp_path / "scanner-data.json"
    monkeypatch.setenv("SCANNER_CACHE_PATH", str(cache_file))
    monkeypatch.setattr("kite_app.scanner_data.equity_universe", lambda kite: [
        {"ticker": "INFY", "company": "Infosys", "token": 408065},
        {"ticker": "TCS", "company": "Tata Consultancy", "token": 2953217},
    ])
    monkeypatch.setattr("kite_app.scanner_data.load_nifty100", lambda: [
        {"ticker": "INFY", "company": "Infosys"},
        {"ticker": "TCS", "company": "Tata Consultancy"},
    ])
    monkeypatch.setattr("kite_app.scanner_data.load_nifty50_symbols", lambda: {"INFY"})
    monkeypatch.setattr("kite_app.scanner_data.time.sleep", lambda _seconds: None)
    kite = FakeKite()

    first = build_scanner_payload(kite, budget_seconds=5)
    second = build_scanner_payload(kite, budget_seconds=5)
    saved = json.loads(cache_file.read_text(encoding="utf-8"))

    assert kite.calls == 2
    assert first["metadata"]["universe"] == 2
    assert first["metadata"]["scanned"] == 2
    assert first["metadata"]["complete"] is True
    assert first["metadata"]["cached_stocks"] == 2
    assert first["stocks"] == []
    assert saved["stocks"][0]["symbol"] == "INFY"
    assert saved["stocks"][0]["instrument_token"] == 408065
    assert saved["stocks"][0]["nifty_flags"] == {"nifty50": True, "nifty100": True}
    assert saved["stocks"][0]["candles"][0]["date"] == "2026-10-01"
    assert saved["stocks"][0]["candles"][0]["open"] == 10.0
    assert "access_token" not in str(first)
    assert second["metadata"]["complete"] is True
    assert kite.calls == 2


def test_scanner_keeps_filling_until_every_symbol_is_recorded(monkeypatch, tmp_path):
    monkeypatch.setenv("SCANNER_CACHE_PATH", str(tmp_path / "scanner-data.json"))
    monkeypatch.setattr("kite_app.scanner_data.equity_universe", lambda kite: [
        {"ticker": "AAA", "company": "A", "token": 1},
        {"ticker": "BBB", "company": "B", "token": 2},
        {"ticker": "CCC", "company": "C", "token": 3},
    ])
    monkeypatch.setattr("kite_app.scanner_data.load_nifty100", lambda: [])
    monkeypatch.setattr("kite_app.scanner_data.load_nifty50_symbols", lambda: set())
    monkeypatch.setattr("kite_app.scanner_data.time.sleep", lambda _seconds: None)
    kite = FakeKite()

    started = build_scanner_payload(kite, budget_seconds=0)
    assert started["metadata"]["universe"] == 3
    assert started["metadata"]["scanned"] == 0
    assert started["metadata"]["complete"] is False
    assert kite.calls == 0

    finished = build_scanner_payload(kite, budget_seconds=30)
    assert finished["metadata"]["scanned"] == 3
    assert finished["metadata"]["complete"] is True
    assert kite.calls == 3


def test_public_payload_returns_only_breakout_rows(monkeypatch, tmp_path):
    fixtures = {row["symbol"]: row["candles"] for row in self_test_fixture()}

    class History:
        def __init__(self) -> None:
            self.calls = 0

        def historical_data(self, token, start, end, interval):
            self.calls += 1
            symbol = "INFY" if token == 1 else "QUIET"
            return fixtures[symbol]

    monkeypatch.setenv("SCANNER_CACHE_PATH", str(tmp_path / "scanner-data.json"))
    monkeypatch.setattr("kite_app.scanner_data.equity_universe", lambda kite: [
        {"ticker": "INFY", "company": "Infosys", "token": 1},
        {"ticker": "QUIET", "company": "Quiet", "token": 2},
    ])
    monkeypatch.setattr("kite_app.scanner_data.load_nifty100", lambda: [])
    monkeypatch.setattr("kite_app.scanner_data.load_nifty50_symbols", lambda: set())
    monkeypatch.setattr("kite_app.scanner_data.time.sleep", lambda _seconds: None)
    kite = History()

    payload = build_scanner_payload(kite, budget_seconds=30)

    assert kite.calls == 2
    assert [row["symbol"] for row in payload["stocks"]] == ["INFY"]
    assert payload["metadata"]["universe"] == 2
    assert payload["metadata"]["scanned"] == 2


def test_ohlc_snapshot_uses_last_price():
    payload = ohlc_snapshot(FakeKite(), ["infy", "INFY", ""])
    assert payload == {"quotes": [{"symbol": "INFY", "last_price": 101.5}]}
