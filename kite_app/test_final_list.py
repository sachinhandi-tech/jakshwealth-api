import kite_app.final_list as final_list


def test_final_list_returns_before_the_model_runs():
    result = final_list.begin_final_list(
        {"api_key": "key", "access_token": "secret-token"},
        launch=False,
    )

    assert result["working"] is True
    assert result["paused"] is False
    assert "secret-token" not in str(result)
    assert any("equities" in line["text"] for line in result["activity"])


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


def test_stop_holds_the_scan_until_continue(monkeypatch):
    from kite_app.desk_progress import resume_scan

    started = []
    monkeypatch.setattr(final_list, "_launch", lambda record: started.append(record["api_key"]))
    resume_scan()
    try:
        stopped = final_list.stop_scan()
        assert stopped["paused"] is True
        assert stopped["working"] is False
        assert "Scan stopped" in stopped["activity"][-1]["text"]

        again = final_list.begin_final_list(
            {"api_key": "key", "access_token": "secret-token"},
        )
        assert again["paused"] is True
        assert again["working"] is False
        assert started == []
        assert "secret-token" not in str(again)

        resumed = final_list.continue_scan({"api_key": "key", "access_token": "secret-token"})
        assert resumed["paused"] is False
        assert started == ["key"]
    finally:
        resume_scan()
