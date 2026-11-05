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
    monkeypatch.setattr(final_list, "_screen_total", lambda saved_count=0: max(saved_count, 3))
    monkeypatch.setattr("kite_app.scanner_data.filter_symbols_to_caps", lambda symbols, segments=None: list(symbols))
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


def test_review_keeps_model_veto_reason_for_the_desk(monkeypatch):
    monkeypatch.setattr(final_list, "_REVIEW_QUEUED", {"INFY"})
    monkeypatch.setattr(final_list, "_REVIEWS", {})
    monkeypatch.setattr(final_list, "_SEEN", {"INFY"})
    monkeypatch.setattr(final_list, "_SCREENED", {"INFY"})
    monkeypatch.setattr(final_list, "_BOOK", {
        "scanned": 1,
        "accepted": 1,
        "setups": [],
        "sell_calls": [],
        "vetoes": [],
    })
    monkeypatch.setattr(final_list, "_FINISHED", False)
    monkeypatch.setattr(final_list, "_WORKING", True)
    monkeypatch.setattr(final_list, "_load_stocks", lambda: [{
        "symbol": "INFY",
        "entry": 10,
        "last_close": 12,
        "gtt_tradable": True,
        "reason": "ready",
    }])
    monkeypatch.setattr(
        "kite_app.algo_layers.select_setups",
        lambda stocks, review=False: {
            "scanned": 1,
            "accepted": 1,
            "setups": [{
                "symbol": "INFY",
                "entry": 10,
                "stop": 9,
                "target": 14,
                "last_close": 12,
                "gtt_tradable": True,
                "reason": "ready",
                "desk": {"book_call": "buy"},
            }],
            "sell_calls": [],
        },
    )

    def fake_review(setups, ask=None):
        setups[0]["ai_decision"] = "stand_aside"
        setups[0]["ai_reason"] = "Filings, news, and lawsuits were not all read, so there is no order."
        setups[0]["gtt_tradable"] = False

    monkeypatch.setattr("kite_app.algo_review.review_setups", fake_review)
    monkeypatch.setattr("kite_app.scan_jobs.equity_work_pending", lambda: False)
    monkeypatch.setattr("kite_app.scanner_data.filter_symbols_to_caps", lambda symbols, segments=None: list(symbols))

    final_list._handle_review({"symbol": "INFY"})
    snapshot = final_list.public_snapshot()

    assert snapshot["setups"] == []
    assert snapshot["vetoes"][0]["symbol"] == "INFY"
    assert "Filings, news, and lawsuits were not all read" in snapshot["vetoes"][0]["ai_reason"]
    assert snapshot["finished"] is True
    joined = " ".join(line["text"] for line in snapshot["activity"])
    assert "INFY" in joined
    assert "did not approve a buy" in joined
    assert "Filings, news, and lawsuits were not all read" in (snapshot["universe_note"] + " " + joined)


def test_review_writes_approved_buys_into_the_book(monkeypatch):
    monkeypatch.setattr(final_list, "_REVIEW_QUEUED", {"INFY"})
    monkeypatch.setattr(final_list, "_REVIEWS", {})
    monkeypatch.setattr(final_list, "_SEEN", {"INFY"})
    monkeypatch.setattr(final_list, "_SCREENED", {"INFY"})
    monkeypatch.setattr(final_list, "_BOOK", {"scanned": 1, "accepted": 1, "setups": [], "sell_calls": []})
    monkeypatch.setattr(final_list, "_FINISHED", False)
    monkeypatch.setattr(final_list, "_WORKING", True)
    monkeypatch.setattr(final_list, "_load_stocks", lambda: [{
        "symbol": "INFY",
        "entry": 10,
        "last_close": 12,
        "gtt_tradable": True,
        "reason": "ready",
    }])
    monkeypatch.setattr(
        "kite_app.algo_layers.select_setups",
        lambda stocks, review=False: {
            "scanned": 1,
            "accepted": 1,
            "setups": [{
                "symbol": "INFY",
                "entry": 10,
                "last_close": 12,
                "gtt_tradable": True,
                "reason": "ready",
            }],
            "sell_calls": [],
        },
    )

    def fake_review(setups, ask=None):
        setups[0]["ai_decision"] = "buy"
        setups[0]["ai_reason"] = "Filings were clean."
        setups[0]["gtt_tradable"] = True

    monkeypatch.setattr("kite_app.algo_review.review_setups", fake_review)
    monkeypatch.setattr("kite_app.scan_jobs.equity_work_pending", lambda: False)
    monkeypatch.setattr("kite_app.scanner_data.filter_symbols_to_caps", lambda symbols, segments=None: list(symbols))

    final_list._handle_review({"symbol": "INFY"})
    snapshot = final_list.public_snapshot()

    assert snapshot["setups"][0]["symbol"] == "INFY"
    assert snapshot["setups"][0]["ai_decision"] == "buy"
    assert snapshot["working"] is False
    assert snapshot["finished"] is True


def test_old_coverage_without_caps_does_not_count(monkeypatch):
    from kite_app import scan_jobs
    from kite_app.scanner_data import set_cap_segments

    set_cap_segments(["large"])
    covered = {
        "book": "equity",
        "scan_all_nse": True,
        "universe": 150,
        "scanned": 150,
        "skipped": 0,
        "signals": [{"symbol": "AAA"}],
    }
    scan_jobs._LISTS.clear()
    scan_jobs._LISTS["short"] = dict(covered)
    scan_jobs._LISTS["long"] = dict(covered)
    try:
        assert scan_jobs._book_covered("equity") is False
        covered["caps"] = ["large"]
        scan_jobs._LISTS["short"] = dict(covered)
        scan_jobs._LISTS["long"] = dict(covered)
        assert scan_jobs._book_covered("equity") is True
    finally:
        scan_jobs._LISTS.clear()
        set_cap_segments(["large", "mid", "small"])


def test_stale_queue_message_does_not_rewrite_small_only_caps(monkeypatch):
    from kite_app.desk_progress import bump_generation, current_generation
    from kite_app.scanner_data import selected_cap_segments, set_cap_segments

    set_cap_segments(["small"])
    bump_generation()
    handled = []

    monkeypatch.setattr(final_list, "_handle_pass", lambda body: handled.append(body))
    monkeypatch.setattr(final_list, "_handle_screen", lambda body: handled.append(body))
    monkeypatch.setattr(final_list, "_handle_review", lambda body: handled.append(body))

    # Old large+small work from before Start from zero must be ignored.
    final_list.handle_message({
        "kind": "screen",
        "symbols": ["AAA"],
        "caps": ["large", "small"],
        "generation": 0,
    })
    final_list.handle_message({
        "kind": "screen",
        "symbols": ["BBB"],
        "caps": ["large", "small"],
    })

    assert handled == []
    assert selected_cap_segments() == ["small"]
    set_cap_segments(["large", "mid", "small"])


def test_same_generation_message_adopts_large_only_on_stale_worker(monkeypatch):
    from kite_app.desk_progress import bump_generation, current_generation
    from kite_app.scanner_data import selected_cap_segments, set_cap_segments

    # Worker still thinks large+mid while the desk already restarted as large-only.
    set_cap_segments(["large", "mid"])
    bump_generation()
    handled = []
    monkeypatch.setattr(final_list, "_handle_screen", lambda body: handled.append(body.get("symbols")))

    final_list.handle_message({
        "kind": "screen",
        "symbols": ["RELIANCE"],
        "caps": ["large"],
        "generation": current_generation(),
    })

    assert handled == [["RELIANCE"]]
    assert selected_cap_segments() == ["large"]
    set_cap_segments(["large", "mid", "small"])


def test_empty_cap_restart_keeps_current_selection():
    from kite_app.scanner_data import selected_cap_segments, set_cap_segments

    set_cap_segments(["large"])
    assert set_cap_segments([]) == ["large"]
    assert selected_cap_segments() == ["large"]
    set_cap_segments(["large", "mid", "small"])


def test_screen_handler_drops_symbols_outside_selected_caps(monkeypatch):
    from kite_app.scanner_data import set_cap_segments

    set_cap_segments(["large"])
    monkeypatch.setattr(final_list, "_SEEN", set())
    monkeypatch.setattr(final_list, "_SCREENED", set())
    monkeypatch.setattr(final_list, "_REVIEW_QUEUED", set())
    monkeypatch.setattr(final_list, "_REVIEWS", {})
    monkeypatch.setattr(final_list, "_BOOK", {"scanned": 0, "accepted": 0, "setups": [], "sell_calls": []})
    monkeypatch.setattr(
        "kite_app.scanner_data.listed_cap_symbols",
        lambda segments=None: {"RELIANCE", "TCS"},
    )
    monkeypatch.setattr(
        final_list,
        "_load_stocks",
        lambda: [
            {"symbol": "RELIANCE", "candles": [{"close": 1}]},
            {"symbol": "MIDCO", "candles": [{"close": 1}]},
        ],
    )
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
        final_list._handle_screen({
            "symbols": ["RELIANCE", "MIDCO", "SMALLCO"],
            "platform_user_id": "user",
            "caps": ["large"],
        })
        assert final_list._SCREENED == {"RELIANCE"}
        assert final_list._BOOK["scanned"] == 1
    finally:
        set_cap_segments(["large", "mid", "small"])


def test_finished_read_is_not_relaunched_on_poll(monkeypatch):
    launched = []
    monkeypatch.setattr(final_list, "_FINISHED", True)
    monkeypatch.setattr(final_list, "_WORKING", False)
    monkeypatch.setattr(final_list, "_SEEN", {"AAA"})
    monkeypatch.setattr(final_list, "_SCREENED", {"AAA"})
    monkeypatch.setattr(final_list, "_REVIEW_QUEUED", set())
    monkeypatch.setattr(final_list, "_load_stocks", lambda: [{"symbol": "AAA"}])
    monkeypatch.setattr("kite_app.scan_jobs.equity_work_pending", lambda: False)
    monkeypatch.setattr(
        "kite_app.equity_queue.enqueue_equity_pass",
        lambda *args, **kwargs: launched.append(True) or True,
    )

    final_list._launch({"api_key": "k", "access_token": "t", "platform_user_id": "user"})

    assert launched == []


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
        assert "NSE" in snap["progress"]["label"]
        assert snap["progress"]["remaining_percent"] == 20
        assert all("6,554" not in line["text"] and "6554" not in line["text"] for line in snap["activity"])
        assert all("Starting NSE" not in line["text"] for line in snap["activity"])
        assert "400 of 500" in snap["activity"][-1]["text"]
    finally:
        clear_activity()


def test_finished_read_hides_progress_meter(monkeypatch):
    from kite_app.desk_progress import clear_activity, note_scan

    clear_activity()
    monkeypatch.setattr(final_list, "_FINISHED", True)
    monkeypatch.setattr(final_list, "_WORKING", False)
    monkeypatch.setattr(final_list, "_FOCUS", "The NSE large, mid, and small cap read is finished.")
    note_scan("equity:price", 5, 495, 0, True)
    note_scan("screen", 95, 100, 0, False, label="names", action="screened")
    try:
        snap = final_list.public_snapshot()
        assert snap["progress"] is None
        assert snap["working"] is False
        assert len(snap["activity"]) == 1
        assert "finished" in snap["activity"][0]["text"]
        assert all("% remaining" not in line["text"] for line in snap["activity"])
        assert all("495" not in line["text"] for line in snap["activity"])
    finally:
        clear_activity()
        monkeypatch.setattr(final_list, "_FINISHED", False)
        monkeypatch.setattr(final_list, "_FOCUS", "")


def test_mark_finished_clears_remaining_chatter(monkeypatch):
    from kite_app.desk_progress import clear_activity, note_activity, note_scan

    clear_activity()
    monkeypatch.setattr(final_list, "_FINISHED", False)
    monkeypatch.setattr(final_list, "_WORKING", True)
    monkeypatch.setattr(final_list, "_SCREENED", {f"S{i}" for i in range(217)})
    monkeypatch.setattr(final_list, "_SEEN", {f"S{i}" for i in range(217)})
    monkeypatch.setattr(final_list, "_BOOK", {"scanned": 217, "accepted": 0, "setups": [], "sell_calls": [], "vetoes": []})
    note_scan("screen", 217, 247, 0, True, label="names", action="screened")
    note_activity("217 of 247 names screened. 12% remaining.")
    try:
        final_list._mark_finished("The NSE small cap read is finished.")
        snap = final_list.public_snapshot()
        assert snap["finished"] is True
        assert snap["working"] is False
        assert snap["progress"] is None
        assert snap["activity"] == [{"text": "The NSE small cap read is finished.", "state": "done"}]
        assert "% remaining" not in snap["universe_note"]
    finally:
        clear_activity()
        monkeypatch.setattr(final_list, "_FINISHED", False)
        monkeypatch.setattr(final_list, "_SCREENED", set())
        monkeypatch.setattr(final_list, "_SEEN", set())


def test_finish_waits_for_in_flight_screens(monkeypatch):
    monkeypatch.setattr(final_list, "_FINISHED", False)
    monkeypatch.setattr(final_list, "_WORKING", True)
    monkeypatch.setattr(final_list, "_SEEN", {"AAA", "BBB", "CCC"})
    monkeypatch.setattr(final_list, "_SCREENED", {"AAA"})
    monkeypatch.setattr(final_list, "_REVIEW_QUEUED", set())
    monkeypatch.setattr(final_list, "_next_symbols", lambda saved=None: [])
    monkeypatch.setattr("kite_app.scan_jobs.equity_work_pending", lambda: False)

    final_list._finish_if_idle()

    assert final_list._FINISHED is False
    assert final_list._screens_pending() is True


def test_late_screen_does_not_revive_finished_read(monkeypatch):
    from kite_app.desk_progress import clear_activity

    clear_activity()
    monkeypatch.setattr(final_list, "_FINISHED", True)
    monkeypatch.setattr(final_list, "_WORKING", False)
    monkeypatch.setattr(final_list, "_FOCUS", "The NSE large, mid, and small cap read is finished.")
    monkeypatch.setattr(final_list, "_SCREENED", {"AAA"})
    called = []
    monkeypatch.setattr(final_list, "_load_stocks", lambda: called.append("load") or [])
    try:
        final_list._handle_screen({
            "symbols": ["BBB"],
            "platform_user_id": "user",
            "caps": ["large"],
        })
        snap = final_list.public_snapshot()
        assert called == []
        assert snap["finished"] is True
        assert snap["progress"] is None
        assert snap["activity"][0]["text"].endswith("finished.")
    finally:
        clear_activity()
        monkeypatch.setattr(final_list, "_FINISHED", False)
        monkeypatch.setattr(final_list, "_SCREENED", set())
        monkeypatch.setattr(final_list, "_FOCUS", "")


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
