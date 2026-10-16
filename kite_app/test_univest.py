import pytest

from kite_app.univest import UnivestParseError, parse_univest


def test_buy_range_stop_and_product():
    text = """
    BUY TATAMOTORS
    Entry: 980-990
    SL: 950
    Target: 1050
    CNC
    """
    parsed = parse_univest(text)
    assert parsed["symbol"] == "TATAMOTORS"
    assert parsed["transaction_type"] == "BUY"
    assert parsed["entry_price"] == 985.0
    assert parsed["entry_low"] == 980.0
    assert parsed["entry_high"] == 990.0
    assert parsed["stop_loss"] == 950.0
    assert parsed["target"] == 1050.0
    assert parsed["product"] == "CNC"
    assert parsed["source"] == "univest"
    assert parsed["signal_kind"] == "entry"


def test_optional_stop_and_multiple_targets():
    text = "SELL RELIANCE\nCMP 2460\nTargets: 2400 / 2350 / 2300\nMIS"
    parsed = parse_univest(text)
    assert parsed["symbol"] == "RELIANCE"
    assert parsed["transaction_type"] == "SELL"
    assert parsed["entry_price"] == 2460.0
    assert parsed["stop_loss"] is None
    assert parsed["target"] == 2400.0
    assert parsed["targets"] == [2400.0, 2350.0, 2300.0]
    assert parsed["product"] == "MIS"


def test_partial_profit_booking():
    text = "Book 50% profit in TATAMOTORS (TATAMOTORS) at 1020. Trail SL to cost."
    parsed = parse_univest(text)
    assert parsed["symbol"] == "TATAMOTORS"
    assert parsed["transaction_type"] == "SELL"
    assert parsed["signal_kind"] == "partial_book"
    assert parsed["entry_price"] == 1020.0
    assert parsed["stop_loss"] is None


def test_explicit_nse_symbol_and_t1_t2():
    text = "NSE: SBIN BUY above 820.50. Stop loss 805. T1: 850 T2: 870. Intraday"
    parsed = parse_univest(text)
    assert parsed["symbol"] == "SBIN"
    assert parsed["transaction_type"] == "BUY"
    assert parsed["entry_price"] == 820.50
    assert parsed["stop_loss"] == 805.0
    assert parsed["targets"] == [850.0, 870.0]
    assert parsed["product"] == "MIS"


def test_malformed_notification_does_not_raise_a_generic_error():
    with pytest.raises(UnivestParseError):
        parse_univest("Market is closed today. No trade.")
