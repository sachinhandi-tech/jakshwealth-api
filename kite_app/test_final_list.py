import kite_app.final_list as final_list


def test_final_list_returns_before_the_model_runs():
    result = final_list.begin_final_list(
        {"api_key": "key", "access_token": "secret-token"},
        launch=False,
    )

    assert result["working"] is True
    assert "secret-token" not in str(result)
    assert any("NSE" in line["text"] for line in result["activity"])


def test_saved_names_reach_the_model_away_from_the_request(monkeypatch):
    monkeypatch.setattr(final_list, "_load_stocks", lambda: [{"symbol": "INFY"}])
    monkeypatch.setattr(final_list, "_LAST_SCREEN", 0.0)
    monkeypatch.setattr(final_list, "_LAST_COUNT", -1)
    monkeypatch.setattr(final_list, "_REVIEWS", {})

    def fake_select(stocks, limit=5, review=True):
        assert review is False
        return {
            "scanned": len(stocks),
            "accepted": 1,
            "setups": [{
                "symbol": "INFY",
                "entry": 10,
                "last_close": 12,
                "gtt_tradable": True,
                "reason": "ready",
            }],
            "sell_calls": [],
        }

    def fake_review(setups, ask=None):
        setups[0]["ai_decision"] = "buy"
        setups[0]["ai_reason"] = "Filings were read."
        setups[0]["gtt_tradable"] = True

    monkeypatch.setattr("kite_app.algo_layers.select_setups", fake_select)
    monkeypatch.setattr("kite_app.algo_review.review_setups", fake_review)

    final_list.refresh_book()
    snapshot = final_list.public_snapshot()

    assert snapshot["setups"][0]["ai_decision"] == "buy"
    assert snapshot["setups"][0]["symbol"] == "INFY"
    assert any("INFY" in line["text"] for line in snapshot["activity"])
