"""Advisory cards become Zerodha limit orders. No live broker call."""

from datetime import date

import pytest

from kite_app.advisory import parse_alert, parse_alerts
from kite_app.broker_orders import OrderRejected, build_orders
from kite_app.univest import UnivestParseError


FUTURES = """
Futures Pick
BANKBARODA 27 OCT FUT
Buy 235.34 234.65 - 235.35
Stoploss 225.0
Target 245.00
Lot size 2925
"""

OPTIONS = """
NIFTY 50
Buy 27 OCT 22750 PE 1 86.25
Buy 27 OCT 23100 PE 1 209.00
Sell 27 OCT 22900 PE 2 128.70
Stoploss amount -2135.25
Target amount 6639.75
Lot size 65
"""

STOCK = """
Stock - Long Term
HFCL-BE
Buy 113.92
Target 269.00
Duration 1-3 years
"""

NFO = [
    {
        "name": "BANKBARODA",
        "tradingsymbol": "BANKBARODA26OCTFUT",
        "instrument_type": "FUT",
        "expiry": date(2026, 10, 27),
        "lot_size": 2925,
        "strike": 0,
    },
    {
        "name": "NIFTY",
        "tradingsymbol": "NIFTY26OCT22750PE",
        "instrument_type": "PE",
        "expiry": date(2026, 10, 27),
        "lot_size": 65,
        "strike": 22750,
    },
    {
        "name": "NIFTY",
        "tradingsymbol": "NIFTY26OCT23100PE",
        "instrument_type": "PE",
        "expiry": date(2026, 10, 27),
        "lot_size": 65,
        "strike": 23100,
    },
    {
        "name": "NIFTY",
        "tradingsymbol": "NIFTY26OCT22900PE",
        "instrument_type": "PE",
        "expiry": date(2026, 10, 27),
        "lot_size": 65,
        "strike": 22900,
    },
]

NSE = [
    {"tradingsymbol": "HFCL-BE", "instrument_type": "EQ", "name": "HFCL"},
]


def test_futures_card_is_one_lot_limit_buy():
    signal = parse_alert(FUTURES)
    orders = build_orders(signal, NFO, NSE, equity_quantity=1)
    assert orders == [
        {
            "exchange": "NFO",
            "tradingsymbol": "BANKBARODA26OCTFUT",
            "transaction_type": "BUY",
            "quantity": 2925,
            "product": "NRML",
            "order_type": "LIMIT",
            "price": 235.34,
        }
    ]
    assert signal["stop_loss"] == 225.0
    assert signal["target"] == 245.0


def test_option_card_places_each_leg_with_its_ratio():
    signal = parse_alert(OPTIONS)
    orders = build_orders(signal, NFO, NSE, equity_quantity=1)
    assert [item["tradingsymbol"] for item in orders] == [
        "NIFTY26OCT22750PE",
        "NIFTY26OCT23100PE",
        "NIFTY26OCT22900PE",
    ]
    assert [item["transaction_type"] for item in orders] == ["BUY", "BUY", "SELL"]
    assert [item["quantity"] for item in orders] == [65, 65, 130]
    assert signal["stop_loss"] is None


def test_stock_card_uses_the_configured_share_count():
    signal = parse_alert(STOCK)
    orders = build_orders(signal, NFO, NSE, equity_quantity=1)
    assert orders[0]["exchange"] == "NSE"
    assert orders[0]["tradingsymbol"] == "HFCL-BE"
    assert orders[0]["transaction_type"] == "BUY"
    assert orders[0]["quantity"] == 1
    assert orders[0]["product"] == "CNC"
    assert orders[0]["price"] == 113.92
    assert signal["target"] == 269.0


def test_wrong_lot_size_is_rejected():
    signal = parse_alert(FUTURES.replace("2925", "100"))
    with pytest.raises(OrderRejected):
        build_orders(signal, NFO, NSE, equity_quantity=1)


def test_plain_equity_text_still_parses():
    signal = parse_alert("BUY TATAMOTORS\nEntry: 980-990\nSL: 950\nTarget: 1050\nCNC")
    assert signal["symbol"] == "TATAMOTORS"
    assert signal["legs"][0]["price"] == 985.0


def test_empty_text_is_rejected():
    with pytest.raises(UnivestParseError):
        parse_alert("Market is closed today. No trade.")


def test_the_same_card_layout_applies_to_every_symbol():
    alerts = parse_alerts(
        """
        RELIANCE 19 NOV FUT
        Sell 1480.50 1475 - 1482
        Stoploss 1510
        Target 1420
        Lot size 500
        Posted: 17 OCT '26
        Stock - Med. Term
        HEROMOTOCO
        Buy 5,267.00
        Target 6000
        """
    )
    assert [item["symbol"] for item in alerts] == ["RELIANCE", "HEROMOTOCO"]
    assert alerts[0]["transaction_type"] == "SELL"
    assert alerts[0]["entry_price"] == 1480.50
    assert alerts[1]["entry_price"] == 5267.0
    assert alerts[1]["product"] == "CNC"


def test_commodity_future_uses_mcx_when_nfo_has_no_contract():
    signal = parse_alert(
        """
        CRUDEOIL 19 NOV FUT
        Buy 5800
        Stoploss 5600
        Target 6200
        Lot size 100
        """
    )
    orders = build_orders(
        signal,
        [],
        [],
        equity_quantity=1,
        mcx=[
            {
                "name": "CRUDEOIL",
                "tradingsymbol": "CRUDEOIL26NOVFUT",
                "instrument_type": "FUT",
                "expiry": date(2026, 11, 19),
                "lot_size": 100,
                "strike": 0,
            }
        ],
    )
    assert orders[0]["exchange"] == "MCX"
    assert orders[0]["tradingsymbol"] == "CRUDEOIL26NOVFUT"
    assert orders[0]["quantity"] == 100
