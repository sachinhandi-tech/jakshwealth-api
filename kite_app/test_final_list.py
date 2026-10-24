import time

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


def test_screening_shows_how_many_names_remain(monkeypatch):
    from kite_app.desk_progress import clear_activity

    clear_activity()
    monkeypatch.setattr(final_list, "_SEEN", set())
    monkeypatch.setattr(final_list, "_SCREENED", set())
    monkeypatch.setattr(final_list, "_REVIEW_QUEUED", set())
    monkeypatch.setattr(final_list, "_REVIEWS", {})
    monkeypatch.setattr(
        final_list,
        "_load_stocks",
        lambda: [{"symbol": "AAA"}, {"symbol": "BBB"}, {"symbol": "CCC"}],
    )
    monkeypatch.setattr(
        final_list,
        "_session_for",
        lambda user: {"platform_user_id": user, "api_key": "k", "access_token": "t"},
    )
    monkeypatch.setattr("kite_app.scan_jobs.ensure_listed_equity_scan", lambda record: None)
    monkeypatch.setattr("kite_app.scan_jobs.equity_work_pending", lambda: False)
    monkeypatch.setattr("kite_app.equity_queue.enqueue_screen_batches", lambda user, symbols: len(symbols))
    monkeypatch.setattr("kite_app.equity_queue.enqueue_equity_pass", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        "kite_app.algo_layers.select_setups",
        lambda stocks, review=False: {
            "scanned": len(stocks),
            "accepted": 0,
            "setups": [],
            "sell_calls": [],
        },
    )
    try:
        final_list._handle_pass({
            "platform_user_id": "00000000-0000-0000-0000-000000000001",
            "wave": 0,
        })
        queued = final_list.public_snapshot()
        assert queued["progress"]["done"] == 0
        assert queued["progress"]["total"] == 3
        assert queued["progress"]["action"] == "screened"
        assert queued["progress"]["remaining_percent"] == 100
        assert "0 of 3 names screened" in queued["activity"][-1]["text"]
        assert "Queued" not in queued["activity"][-1]["text"]

        final_list._handle_screen({"symbols": ["AAA"], "platform_user_id": "user"})
        screened = final_list.public_snapshot()
        assert screened["progress"]["done"] == 1
        assert screened["progress"]["total"] == 3
        assert screened["progress"]["remaining_percent"] == 67
        assert "1 of 3 names screened" in screened["activity"][-1]["text"]
        assert "67% remaining" in screened["activity"][-1]["text"]
        assert all("Screening a batch" not in line["text"] for line in screened["activity"])
    finally:
        clear_activity()


def test_live_book_count_is_not_replaced_by_the_old_cache():
    from kite_app.desk_progress import clear_activity, note_activity, note_scan

    clear_activity()
    note_activity("NSE equities: read 500 of 500 names.")
    note_activity("Starting NSE equities.")
    note_activity("Asking Zerodha for the NSE equities list.")
    note_scan("equity:price", 400, 500, 0, True)
    note_scan("screen", 24, 6554, 0, True, label="names", action="screened")
    try:
        snap = final_list.public_snapshot()
        assert snap["progress"]["done"] == 400
        assert snap["progress"]["total"] == 500
        assert snap["progress"]["label"] == "NSE equities"
        assert snap["progress"]["remaining_percent"] == 20
        assert all("6,554" not in line["text"] and "6554" not in line["text"] for line in snap["activity"])
        assert all("Starting NSE" not in line["text"] for line in snap["activity"])
        assert "400 of 500" in snap["activity"][-1]["text"]
    finally:
        clear_activity()


def test_stop_holds_the_scan_until_continue(monkeypatch):
    from kite_app.desk_progress import resume_scan

    started = []
    forgotten = []
    monkeypatch.setattr(final_list, "_launch", lambda record: started.append(record["api_key"]))
    monkeypatch.setattr(
        "kite_app.scan_jobs.forget_saved_scans",
        lambda: forgotten.append(True),
    )
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
        for _ in range(50):
            if forgotten and started:
                break
            time.sleep(0.02)
        assert started == ["key"]
        assert forgotten == [True]
        assert "secret-token" not in str(resumed)
    finally:
        resume_scan()
