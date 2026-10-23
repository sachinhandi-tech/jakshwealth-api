import threading
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from kiteconnect.exceptions import KiteException

from kite_app.gtt_orders import CREATED_MESSAGE, clear_recent_placements, gtt_state, live_gtt

IST = ZoneInfo("Asia/Kolkata")
OTHER_MUTATIONS = ("place_order", "modify_order", "cancel_order", "modify_gtt", "delete_gtt")


def instrument():
    return {"exchange": "NSE", "instrument_type": "EQ", "tradingsymbol": "SIEMENS", "tick_size": "0.1"}


def order(**overrides):
    payload = {"symbol": "SIEMENS", "quantity": 5, "buy_price": "3903.26", "stoploss": "1", "last_price": "4043"}
    payload.update(overrides)
    return payload


def active_buy(symbol: str, trigger_id, trigger):
    return {
        "id": trigger_id,
        "status": "active",
        "condition": {"tradingsymbol": symbol, "trigger_values": [trigger]},
        "orders": [{"transaction_type": "BUY"}],
    }


def kite(**overrides):
    client = Mock()
    client.get_gtts.return_value = overrides.get("gtts", [])
    client.orders.return_value = overrides.get("orders", [])
    client.positions.return_value = overrides.get("positions", {"net": []})
    client.holdings.return_value = overrides.get("holdings", [])
    client.instruments.return_value = overrides.get("instruments", [instrument()])
    client.place_gtt.return_value = overrides.get("placed", {"trigger_id": 4242})
    for name in OTHER_MUTATIONS:
        setattr(client, name, Mock(side_effect=AssertionError(name)))
    return client


def assert_no_other_mutations(client: Mock) -> None:
    for name in OTHER_MUTATIONS:
        getattr(client, name).assert_not_called()


def test_state_is_ready_and_rounds_to_the_tick_without_placing():
    clear_recent_placements()
    client = kite()
    rows = gtt_state(client, [order()])
    assert rows[0]["buy_price"] == 3903.3
    assert rows[0]["stoploss"] == 3708.1
    assert rows[0]["tick_size"] == 0.1
    assert rows[0]["quantity"] == 25
    assert rows[0]["buy_status"] == "ready"
    assert rows[0]["account_state"] == "clear"
    assert rows[0]["message"] == "Ready for buy GTT placement."
    assert rows[0]["stoploss_status"] == "planned_after_buy"
    client.place_gtt.assert_not_called()
    assert_no_other_mutations(client)


def test_live_places_one_buy_gtt_and_a_repeat_is_already_active():
    clear_recent_placements()
    client = kite()

    def place(**kwargs):
        client.get_gtts.return_value = [active_buy("SIEMENS", 4242, kwargs["trigger_values"][0])]
        return {"trigger_id": 4242}

    client.place_gtt.side_effect = place
    created = live_gtt(client, [order()], confirm_live=True)[0]
    assert created["buy_status"] == "success"
    assert created["buy_trigger_id"] == "4242"
    assert created["message"] == CREATED_MESSAGE
    assert created["stoploss_trigger_id"] is None
    assert created["stoploss_status"] == "planned_after_buy"
    sent = client.place_gtt.call_args.kwargs
    assert sent["trigger_type"] == "single"
    assert sent["tradingsymbol"] == "SIEMENS"
    assert sent["exchange"] == "NSE"
    assert sent["trigger_values"] == [3903.3]
    assert sent["last_price"] == 4043.0
    assert sent["orders"] == [{
        "transaction_type": "BUY",
        "quantity": 25,
        "price": 3903.3,
        "order_type": "LIMIT",
        "product": "CNC",
    }]

    again = live_gtt(kite(gtts=[active_buy("SIEMENS", 4242, 3903.3)]), [order()], confirm_live=True)[0]
    assert again["buy_status"] == "already_active"
    assert again["buy_trigger_id"] == "4242"
    assert again["message"] == "Skipped: buy GTT already active."
    assert client.place_gtt.call_count == 1
    assert_no_other_mutations(client)


def test_repeat_does_not_place_again_when_the_kite_list_is_stale():
    clear_recent_placements()
    client = kite()
    first = live_gtt(client, [order()], confirm_live=True)[0]
    second = live_gtt(client, [order()], confirm_live=True)[0]
    assert first["buy_trigger_id"] == "4242"
    assert second["buy_status"] == "already_active"
    assert second["buy_trigger_id"] == "4242"
    assert client.place_gtt.call_count == 1


def test_concurrent_requests_place_one_gtt():
    clear_recent_placements()
    client = kite()
    placed = []

    def place(**kwargs):
        placed.append(kwargs["tradingsymbol"])
        client.get_gtts.return_value = [active_buy("SIEMENS", 4242, kwargs["trigger_values"][0])]
        return {"trigger_id": 4242}

    client.place_gtt.side_effect = place
    results = []

    def run():
        results.append(live_gtt(client, [order()], confirm_live=True)[0]["buy_trigger_id"])

    threads = [threading.Thread(target=run) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count("4242") == 8
    assert placed == ["SIEMENS"]


def test_confirm_live_false_rejects_before_any_kite_call():
    clear_recent_placements()
    client = kite()
    try:
        live_gtt(client, [order()], confirm_live=False)
    except Exception as exc:
        assert "confirm_live" in str(exc)
    else:
        raise AssertionError("confirm_live false was accepted")
    client.get_gtts.assert_not_called()
    client.place_gtt.assert_not_called()
    assert_no_other_mutations(client)


def test_equity_above_one_lakh_is_not_sent():
    clear_recent_placements()
    client = kite()
    row = live_gtt(client, [order(buy_price="150000", last_price="151000")], confirm_live=True)[0]
    assert row["quantity"] == 0
    assert row["buy_status"] == "failed"
    assert row["message"] == "One lakh rupees does not buy one share at this price."
    client.place_gtt.assert_not_called()


def test_future_and_commodity_buy_one_lot():
    clear_recent_placements()
    future = kite(instruments=[{
        "exchange": "NFO",
        "instrument_type": "FUT",
        "tradingsymbol": "RELIANCE24NOVFUT",
        "tick_size": "0.05",
        "lot_size": 250,
    }])
    row = live_gtt(future, [order(symbol="RELIANCE24NOVFUT", exchange="NFO", buy_price="2500", last_price="2510")], confirm_live=True)[0]
    sent = future.place_gtt.call_args.kwargs
    assert row["buy_status"] == "success"
    assert sent["exchange"] == "NFO"
    assert sent["orders"][0]["quantity"] == 250
    assert sent["orders"][0]["product"] == "NRML"
    assert_no_other_mutations(future)

    missing = kite(instruments=[{
        "exchange": "MCX",
        "instrument_type": "FUT",
        "tradingsymbol": "CRUDEOIL24NOVFUT",
        "tick_size": "1",
    }])
    blocked = live_gtt(missing, [order(symbol="CRUDEOIL24NOVFUT", exchange="MCX", buy_price="6000", last_price="6100")], confirm_live=True)[0]
    assert blocked["buy_status"] == "failed"
    assert blocked["message"] == "Kite did not return a lot size for this contract."
    missing.place_gtt.assert_not_called()


def test_trigger_at_or_above_ltp_is_not_sent():
    clear_recent_placements()
    client = kite()
    row = live_gtt(client, [order(buy_price="4100", last_price="4043")], confirm_live=True)[0]
    assert row["buy_status"] == "failed"
    assert row["message"] == "Buy trigger must be below the last price."
    client.place_gtt.assert_not_called()


def test_broker_rejection_is_returned_and_no_other_order_method_runs():
    clear_recent_placements()
    client = kite()
    client.place_gtt.side_effect = KiteException("Trigger price is not a multiple of tick size")
    row = live_gtt(client, [order()], confirm_live=True)[0]
    assert row["buy_status"] == "failed"
    assert row["message"] == "Unable to place buy GTT: Trigger price is not a multiple of tick size"
    assert_no_other_mutations(client)


def test_existing_gtt_day_order_position_and_invalid_rows_do_not_place(tmp_path):
    del tmp_path
    clear_recent_placements()
    today = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    yesterday = (datetime.now(IST) - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    client = kite(
        gtts=[{
            "id": 55,
            "status": "active",
            "condition": {"tradingsymbol": "INFY", "trigger_values": [1500]},
            "orders": [{"transaction_type": "BUY"}],
        }, {
            "id": 99,
            "status": "active",
            "condition": {"tradingsymbol": "RELIANCE", "trigger_values": [1300]},
            "orders": [{"transaction_type": "SELL"}],
        }],
        orders=[
            {"order_id": "B1", "tradingsymbol": "TCS", "exchange": "NSE", "transaction_type": "BUY", "product": "CNC", "status": "OPEN", "order_timestamp": today},
            {"order_id": "OLD", "tradingsymbol": "WIPRO", "exchange": "NSE", "transaction_type": "BUY", "product": "CNC", "status": "COMPLETE", "order_timestamp": yesterday},
            {"order_id": "CXL", "tradingsymbol": "SBIN", "exchange": "NSE", "transaction_type": "BUY", "product": "CNC", "status": "CANCELLED", "order_timestamp": today},
        ],
        positions={"net": [{"tradingsymbol": "HDFCBANK", "quantity": 0}, {"tradingsymbol": "RELIANCE", "quantity": 3}]},
        holdings=[{"tradingsymbol": "ITC", "quantity": 2, "t1_quantity": 1}],
        instruments=[
            instrument(),
            {"exchange": "NSE", "instrument_type": "EQ", "tradingsymbol": "INFY", "tick_size": "0.05"},
            {"exchange": "NSE", "instrument_type": "EQ", "tradingsymbol": "TCS", "tick_size": "0.1"},
            {"exchange": "NSE", "instrument_type": "EQ", "tradingsymbol": "WIPRO", "tick_size": "0.05"},
            {"exchange": "NSE", "instrument_type": "EQ", "tradingsymbol": "SBIN", "tick_size": "0.05"},
            {"exchange": "NSE", "instrument_type": "EQ", "tradingsymbol": "RELIANCE", "tick_size": "0.1"},
            {"exchange": "NSE", "instrument_type": "EQ", "tradingsymbol": "ITC", "tick_size": "0.05"},
            {"exchange": "NSE", "instrument_type": "EQ", "tradingsymbol": "AXISBANK", "tick_size": "0.05"},
        ],
    )
    rows = live_gtt(client, [
        order(symbol="INFY", buy_price="1500", last_price="1510"),
        order(symbol="TCS", buy_price="4000", last_price="4100"),
        order(symbol="WIPRO", buy_price="250", last_price="260"),
        order(symbol="SBIN", buy_price="800", last_price="810"),
        order(symbol="RELIANCE", buy_price="1400", last_price="1410"),
        order(symbol="ITC", buy_price="450", last_price="460"),
        order(symbol="SIEMENS", buy_price=None, last_price="4043"),
        order(symbol="AXISBANK", buy_price="1000", last_price=None),
        order(symbol="NOSYM", buy_price="10", last_price="11"),
    ], confirm_live=True)
    by_symbol = {row["symbol"]: row for row in rows}
    assert by_symbol["INFY"]["message"] == "Skipped: buy GTT already active."
    assert by_symbol["INFY"]["buy_trigger_id"] == "55"
    assert by_symbol["TCS"]["message"] == "Skipped: day BUY order already exists."
    assert by_symbol["TCS"]["day_buy_order_id"] == "B1"
    assert by_symbol["WIPRO"]["buy_status"] == "success"
    assert by_symbol["SBIN"]["buy_status"] == "success"
    assert by_symbol["RELIANCE"]["message"] == "Skipped: existing position/holding quantity is 3."
    assert by_symbol["RELIANCE"]["stoploss_trigger_id"] == "99"
    assert by_symbol["ITC"]["message"] == "Skipped: existing position/holding quantity is 3."
    assert by_symbol["SIEMENS"]["message"] == "Buy price is not available for this row."
    assert by_symbol["AXISBANK"]["message"] == "Waiting for LTP."
    assert by_symbol["NOSYM"]["message"] == "Trigger price should be a multiple of tick size."
    assert client.place_gtt.call_count == 2
    assert_no_other_mutations(client)


def test_only_place_gtt_is_used_to_create_the_order():
    root = Path(__file__).resolve().parent
    allowed = {"gtt_orders.py"}
    banned = OTHER_MUTATIONS
    for name in ("gtt_orders.py", "main.py"):
        text = (root / name).read_text(encoding="utf-8")
        for method in banned:
            assert method not in text
        if name in allowed:
            assert "place_gtt" in text
    assert "place_gtt" not in (root / "main.py").read_text(encoding="utf-8")
    assert "DUMMY-" not in (root / "gtt_orders.py").read_text(encoding="utf-8")
