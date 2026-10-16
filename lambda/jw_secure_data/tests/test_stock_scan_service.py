import pytest

from features.stock_scan import service


def test_universe_info_midcap():
    info = service.universe_info("midcap")
    assert info["segment"] == "midcap"
    assert info["symbolCount"] == 150
    assert info["source"] == "nifty_midcap150.csv"


def test_universe_info_smallcap():
    info = service.universe_info("smallcap")
    assert info["segment"] == "smallcap"
    assert info["symbolCount"] == 250
    assert info["source"] == "nifty_smallcap250.csv"


def test_universe_info_custom():
    info = service.universe_info("custom")
    assert info["segment"] == "custom"
    assert info["symbolCount"] == 0
    assert info["source"] == "user-provided symbols"


def test_run_scan_custom_symbols_sets_segment():
    payload = {
        "symbols": ["RELIANCE", "TCS"],
        "minScore": 80,
        "strictRsi30": False,
        "sleep": 0,
        "maxWorkers": 2,
    }
    body = service.run_scan(payload)
    assert body["universeSegment"] == "custom"
    assert body["scannedCount"] == 2


def test_ranked_filter_requires_score_and_strict_rsi():
    row = {
        "Scan_Status": "OK",
        "Score": 85,
        "RSI_Valid": False,
    }
    assert service._passes_ranked_filter(row, 80, strict_rsi_30=True) is False
    assert service._passes_ranked_filter(row, 80, strict_rsi_30=False) is True


def test_ranked_filter_rejects_low_score():
    row = {
        "Scan_Status": "OK",
        "Score": 70,
        "RSI_Valid": True,
    }
    assert service._passes_ranked_filter(row, 80, strict_rsi_30=True) is False


def test_run_scan_ranked_candidates_respect_filters():
    payload = {
        "symbols": ["RELIANCE"],
        "minScore": 80,
        "strictRsi30": True,
        "sleep": 0,
    }
    body = service.run_scan(payload)
    assert body["rankedCandidateCount"] == len(body["rankedCandidates"])
    for row in body["rankedCandidates"]:
        assert row["Scan_Status"] == "OK"
        assert row["Score"] >= 80
        assert row["RSI_Valid"] is True
