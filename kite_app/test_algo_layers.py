from datetime import date, timedelta

from kite_app.algo_layers import backtest_symbol, combine_books, evaluate_stock, select_setups, walk_exit
from kite_app.gtt_orders import arm_exit


def _candle(index, close, high=None, low=None, volume=1000, open_price=None):
    high = close + 1 if high is None else high
    low = close - 1 if low is None else low
    open_price = close if open_price is None else open_price
    return {
        "date": (date(2026, 1, 1) + timedelta(days=index)).isoformat(),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


def _quiet(count):
    return [_candle(index, 100) for index in range(count)]


def _retest_stock(symbol="INFY", exchange="NSE", instrument_type="EQ"):
    candles = _quiet(70)
    candles[60] = _candle(60, close=108, open_price=100, high=110, low=90, volume=4000)
    candles[61] = _candle(61, close=112, high=120, low=100, volume=1000)
    candles[-1] = _candle(len(candles) - 1, close=101, high=102, low=100, volume=1000)
    return {
        "symbol": symbol,
        "company_name": f"{symbol} Ltd",
        "exchange": exchange,
        "instrument_type": instrument_type,
        "instrument_token": 1,
        "candles": candles,
    }


def test_equity_retest_is_ranked_with_a_2r_target():
    result = select_setups([_retest_stock(), _retest_stock("QUIET")])
    assert result["scanned"] == 2
    symbols = [item["symbol"] for item in result["setups"]]
    assert "INFY" in symbols
    setup = next(item for item in result["setups"] if item["symbol"] == "INFY")
    assert setup["gtt_tradable"] is False
    assert setup["ai_decision"] == "unavailable"
    assert setup["product"] == "CNC"
    risk = setup["entry"] - setup["stop"]
    assert setup["target"] == round(setup["entry"] + 2 * risk, 4)
    assert setup["stop"] < setup["entry"] < setup["last_close"] < setup["target"]
    assert "3" in setup["reason"] or "times" in setup["reason"]
    assert "Sector momentum is not scored" in setup["reason"]
    assert setup["quantity"] == 1000
    assert setup["budget_inr"] == 100000
    assert "one lakh" in setup["reason"]
    assert setup["screens"] == {
        "moving_average": True,
        "price_volume": True,
        "rsi_momentum_atr": True,
    }


def test_moving_average_names_join_the_book_without_a_volume_breakout():
    stock = _retest_stock("WIPRO")
    for candle in stock["candles"]:
        candle["volume"] = 1000
    stock["on_moving_average_list"] = True
    found = evaluate_stock(stock)
    assert found is not None
    assert found["screens"]["moving_average"] is True
    assert found["screens"]["price_volume"] is False
    assert "moving-average crossover list" in found["reason"]
    assert "RSI" in found["reason"]
    assert "ATR" in found["reason"]
    book = select_setups([stock])
    assert book["setups"] == []
    assert "price and volume expansion" in book["rejected"][0]["reason"]
    assert "not sent to the model" in book["rejected"][0]["reason"]

    flat = {
        "symbol": "FLAT",
        "company_name": "Flat Ltd",
        "exchange": "NSE",
        "instrument_type": "EQ",
        "candles": _quiet(70),
    }
    assert evaluate_stock(flat) is None
    merged = combine_books(
        [stock],
        [{"symbol": "TCS", "company_name": "TCS Ltd", "crossover_type": "bullish"}],
        [{"symbol": "TCS", "company_name": "TCS Ltd", "candles": _quiet(70)}],
    )
    symbols = {item["symbol"] for item in merged}
    assert symbols == {"WIPRO", "TCS"}
    tcs = next(item for item in merged if item["symbol"] == "TCS")
    assert tcs["on_moving_average_list"] is True
    assert len(tcs["candles"]) == 70


def _checks(**overrides):
    checks = {name: "pass" for name in ("trend", "participation", "volatility", "asymmetry", "invalidation")}
    checks.update(overrides)
    return checks


def test_model_buy_confirms_the_book_and_a_veto_blocks_the_gtt(monkeypatch):
    from kite_app.algo_review import review_setups

    setup = select_setups([_retest_stock()])["setups"][0]
    assert setup["desk"]["book_call"] == "buy"
    assert setup["desk"]["sma200"] is None
    assert len(setup["desk"]["tape"]) == 12
    setup["gtt_tradable"] = True
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    def allow(_key, _model, facts):
        assert facts["symbol"] == "INFY"
        assert "llm" not in facts
        assert facts["desk"]["book_call"] == "buy"
        assert "risk_pct" in facts["desk"]
        return "buy", "Entry 100, stop under it, and volume is above 3 times.", _checks()

    review_setups([setup], ask=allow)
    assert setup["gtt_tradable"] is True
    assert setup["ai_decision"] == "buy"
    assert setup["ai_checks"]["trend"] == "pass"

    def veto(_key, _model, _facts):
        return "buy", "Trend is only 1 point above the 50 SMA.", _checks(trend="fail")

    setup["gtt_tradable"] = True
    review_setups([setup], ask=veto)
    assert setup["gtt_tradable"] is False
    assert setup["ai_decision"] == "stand_aside"


def test_model_sell_is_a_call_and_not_an_order(monkeypatch):
    from kite_app.algo_layers import evaluate_stock
    from kite_app.algo_review import review_setups

    stock = _retest_stock()
    stock["candles"][-1] = _candle(len(stock["candles"]) - 1, close=101, high=130, low=70, volume=1000)
    decision = evaluate_stock(stock)
    assert decision["desk"]["book_call"] == "sell"
    assert decision["gtt_tradable"] is True
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    def agree(_key, _model, _facts):
        return "sell", "The last bar is wider than 2.5 ATR and the close is 101.", _checks(invalidation="fail")

    review_setups([decision], ask=agree)
    assert decision["ai_decision"] == "sell"
    assert decision["gtt_tradable"] is False
    assert "No short GTT is sent." in decision["ai_reason"]

    def promote(_key, _model, _facts):
        return "buy", "Close is still 101, so the long remains.", _checks()

    decision["gtt_tradable"] = True
    review_setups([decision], ask=promote)
    assert decision["ai_decision"] == "stand_aside"
    assert decision["gtt_tradable"] is False


def test_model_cannot_promote_a_derivative_or_invent_filings():
    from kite_app.algo_review import _INSTRUCTION, review_setups

    assert "Do not invent filings, news, or lawsuits." in _INSTRUCTION
    setup = select_setups([_retest_stock("CRUDEOIL", "MCX", "FUT")])["setups"][0]
    setup["gtt_tradable"] = False

    def allow(_key, _model, _facts):
        return "buy", "The stop is under 100 and the volume multiple is above 3.", _checks()

    import os
    os.environ["LLM_API_KEY"] = "test-key"
    try:
        review_setups([setup], ask=allow)
    finally:
        os.environ.pop("LLM_API_KEY", None)
    assert setup["gtt_tradable"] is False
    assert setup["ai_decision"] == "buy"


def test_derivatives_are_one_lot_and_not_delivery_orders():
    from kite_app.algo_layers import evaluate_stock

    future = evaluate_stock(_retest_stock("RELIANCE", "NFO", "FUT"))
    option = evaluate_stock(_retest_stock("RELIANCE", "NFO", "CE"))
    commodity = evaluate_stock(_retest_stock("CRUDEOIL", "MCX", "FUT"))
    assert future["gtt_tradable"] is True
    assert option["gtt_tradable"] is True
    assert commodity["gtt_tradable"] is True
    assert future["quantity_basis"] == "one_lot"
    assert future["quantity"] is None
    assert future["product"] == "NRML"
    assert "one lot" in commodity["reason"]
    assert "equity delivery" in commodity["reason"]


def test_walk_exit_uses_the_stop_when_one_bar_hits_both():
    future = [{"high": 130, "low": 80, "close": 100}]
    assert walk_exit(future, entry=100, stop=90, target=120)["exit_reason"] == "stop"
    assert walk_exit([{"high": 121, "low": 99, "close": 120}], 100, 90, 120)["r_multiple"] == 2
    assert walk_exit([{"high": 101, "low": 89, "close": 90}], 100, 90, 120)["r_multiple"] == -1


def test_backtest_summary_is_computed_from_the_trades():
    stock = _retest_stock()
    rising = []
    for offset in range(1, 8):
        price = 101 + offset * 5
        rising.append(_candle(len(stock["candles"]) + offset, price, high=price + 2, low=price - 1))
    stock["candles"].extend(rising)
    summary = backtest_symbol(stock)
    assert summary["trades"] >= 1
    assert summary["expectancy_r"] == round(
        sum(item["r_multiple"] for item in summary["history"]) / summary["trades"],
        4,
    )


def test_arm_exit_places_one_two_leg_sell_gtt_for_a_holding():
    client = _kite(holdings=[{"tradingsymbol": "INFY", "quantity": 2}])
    rows = arm_exit(client, [{"symbol": "INFY", "last_price": 101, "stoploss": 90, "target": 120}], True)
    sent = client.place_gtt.call_args.kwargs
    assert rows[0]["stoploss_status"] == "success"
    assert sent["trigger_type"] == "two-leg"
    assert sent["orders"][0]["transaction_type"] == "SELL"
    assert sent["orders"][1]["price"] == 120
    assert sent["orders"][0]["quantity"] == 2
    client.place_order.assert_not_called()


def test_unread_filings_news_and_lawsuits_block_the_call(monkeypatch):
    from kite_app.algo_review import _read_source, review_setups

    def fail(_url):
        raise OSError("down")

    missed = _read_source("read_filings", {"symbol": "INFY", "company_name": "Infosys"}, get=fail)
    assert missed["status"] == "unavailable"
    assert missed["text"] == "This source returned no text."
    assert "Infosys" not in missed["text"]
    setup = select_setups([_retest_stock()])["setups"][0]
    setup["gtt_tradable"] = True
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    def allow(_key, _model, facts):
        assert facts["company_name"] == "INFY Ltd"
        return (
            "buy",
            "Entry 100 and volume above 3.",
            _checks(),
            [
                {"name": "read_filings", "status": "unavailable"},
                {"name": "read_news", "status": "ready"},
                {"name": "read_lawsuits", "status": "ready"},
            ],
        )

    review_setups([setup], ask=allow)
    assert setup["ai_decision"] == "stand_aside"
    assert setup["gtt_tradable"] is False
    assert "not all read" in setup["ai_reason"]


def test_final_list_loads_the_model_key_before_it_refuses(monkeypatch):
    from kite_app.algo_review import review_setups

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    def load():
        monkeypatch.setenv("LLM_API_KEY", "loaded-key")
        monkeypatch.setenv("LLM_MODEL", "grok-4.7")

    monkeypatch.setattr("kite_app.models.load_platform_config", load)
    seen = {}

    def ask(key, model, _facts):
        seen["key"] = key
        seen["model"] = model
        return "stand_aside", "Entry is 100 and the volume multiple is 3.", _checks()

    setup = {"symbol": "INFY", "reason": "Book.", "gtt_tradable": False, "desk": {"book_call": "stand_aside"}}
    review_setups([setup], ask=ask)
    assert seen == {"key": "loaded-key", "model": "grok-4.7"}
    assert setup["ai_decision"] == "stand_aside"


def test_grok_model_posts_to_xai_and_returns_only_the_tool_text(monkeypatch):
    import json
    from kite_app import algo_review

    calls = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout=30):
        body = json.loads(request.data.decode("utf-8"))
        calls.append((request.full_url, dict(request.header_items()), body))
        if len(calls) == 1:
            return Response({
                "id": "resp_1",
                "output": [
                    {"type": "function_call", "name": "read_filings", "call_id": "call_1", "arguments": "{}"},
                    {"type": "function_call", "name": "read_news", "call_id": "call_2", "arguments": "{}"},
                    {"type": "function_call", "name": "read_lawsuits", "call_id": "call_3", "arguments": "{}"},
                ],
            })
        return Response({
            "id": "resp_2",
            "output": [{
                "type": "message",
                "content": [{
                    "type": "output_text",
                    "text": json.dumps({
                        "decision": "stand_aside",
                        "reason": "The filing names the company and the last close is 101.",
                        "checks": _checks(),
                    }),
                }],
            }],
        })

    monkeypatch.setattr(algo_review.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(algo_review, "lookup_text", lambda *_args, **_kwargs: "Annual filing text")
    decision, reason, checks, sources = algo_review._ask_grok(
        "grok-test",
        "grok-4.7",
        {"symbol": "INFY", "company_name": "Infosys"},
    )
    assert decision == "stand_aside"
    assert "101" in reason
    assert checks["trend"] == "pass"
    assert [item["name"] for item in sources] == ["read_filings", "read_news", "read_lawsuits"]
    assert calls[0][0] == "https://api.x.ai/v1/responses"
    assert calls[0][1]["Authorization"] == "Bearer grok-test"
    assert "x-api-key" not in {name.lower() for name in calls[0][1]}
    assert calls[0][2]["model"] == "grok-4.7"
    assert "search_parameters" not in calls[0][2]
    assert calls[0][2]["tools"][0]["name"] == "read_filings"
    assert calls[1][2]["previous_response_id"] == "resp_1"
    assert calls[1][2]["input"][0]["output"] == "Annual filing text"
    assert "anthropic.com" not in calls[0][0]
    assert calls[0][2]["store"] is True


def test_grok_reads_json_wrapped_in_other_text(monkeypatch):
    import json
    from kite_app import algo_review

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            answer = {
                "decision": "stand_aside",
                "reason": "The last close is 101 and volume is 3 times.",
                "checks": _checks(),
            }
            return json.dumps({
                "id": "resp_1",
                "output": [{
                    "type": "message",
                    "content": [{"type": "output_text", "text": "Final call:\n```json\n" + json.dumps(answer) + "\n```"}],
                }],
            }).encode("utf-8")

    monkeypatch.setattr(algo_review.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    decision, reason, checks, _sources = algo_review._ask_grok("grok-test", "grok-4.7", {"symbol": "INFY"})
    assert decision == "stand_aside"
    assert "101" in reason
    assert checks["trend"] == "pass"


def test_model_http_failure_names_the_status_and_hides_the_key(monkeypatch):
    import io
    import urllib.error
    from kite_app.algo_review import review_setups

    def fail(_request, timeout=45):
        body = b'{"error":{"message":"Incorrect API key xai-secretvalue"}}'
        raise urllib.error.HTTPError("https://api.x.ai/v1/responses", 401, "Unauthorized", {}, io.BytesIO(body))

    monkeypatch.setattr("urllib.request.urlopen", fail)
    monkeypatch.setenv("LLM_API_KEY", "xai-secretvalue")
    monkeypatch.setenv("LLM_MODEL", "grok-4.7")
    setup = {"symbol": "INFY", "reason": "Book.", "gtt_tradable": False, "desk": {"book_call": "stand_aside"}}
    review_setups([setup])
    assert "HTTP 401" in setup["ai_reason"]
    assert "Incorrect API key" in setup["ai_reason"]
    assert "xai-secretvalue" not in setup["ai_reason"]
    assert setup["gtt_tradable"] is False


def test_arm_exit_waits_until_the_buy_is_held():
    client = _kite()
    rows = arm_exit(client, [{"symbol": "INFY", "last_price": 101, "stoploss": 90, "target": 120}], True)
    assert rows[0]["stoploss_status"] == "planned_after_buy"
    client.place_gtt.assert_not_called()


def _kite(holdings=None):
    from unittest.mock import Mock

    client = Mock()
    client.get_gtts.return_value = []
    client.orders.return_value = []
    client.positions.return_value = {"net": []}
    client.holdings.return_value = holdings or []
    client.instruments.return_value = [{
        "exchange": "NSE",
        "instrument_type": "EQ",
        "tradingsymbol": "INFY",
        "tick_size": "0.05",
    }]
    client.place_gtt.return_value = {"trigger_id": 77}
    return client
