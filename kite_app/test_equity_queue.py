import json

import kite_app.final_list as final_list
from kite_app.equity_queue import send_bodies


class FakeQueue:
    def __init__(self):
        self.batches = []

    def send_message_batch(self, QueueUrl, Entries):
        assert QueueUrl == "https://sqs.example/equity"
        assert len(Entries) <= 10
        self.batches.append(Entries)
        return {"Successful": [{"Id": item["Id"]} for item in Entries], "Failed": []}


def test_send_message_batch_splits_after_ten(monkeypatch):
    fake = FakeQueue()
    monkeypatch.setattr("kite_app.equity_queue.queue_url", lambda client=None: "https://sqs.example/equity")
    bodies = [{"kind": "screen", "symbol": f"S{index}"} for index in range(11)]

    sent = send_bodies(bodies, client=fake)

    assert sent == 11
    assert [len(batch) for batch in fake.batches] == [10, 1]
    assert "access_token" not in json.dumps(fake.batches)


def test_screen_batch_queues_the_model_without_calling_it(monkeypatch):
    monkeypatch.setattr(final_list, "_load_stocks", lambda: [{"symbol": "INFY"}])
    monkeypatch.setattr(final_list, "_REVIEW_QUEUED", set())
    monkeypatch.setattr(final_list, "_REVIEWS", {})
    monkeypatch.setattr(final_list, "_BOOK", {"scanned": 0, "accepted": 0, "setups": [], "sell_calls": []})

    def fake_select(stocks, limit=5, review=True):
        assert review is False
        return {
            "scanned": 1,
            "accepted": 1,
            "setups": [{"symbol": "INFY", "entry": 1, "last_close": 2, "reason": "ready"}],
            "sell_calls": [],
        }

    queued = []

    def fake_reviews(user, symbols):
        assert user == "user-1"
        queued.extend(symbols)
        return len(symbols)

    monkeypatch.setattr("kite_app.algo_layers.select_setups", fake_select)
    monkeypatch.setattr("kite_app.equity_queue.enqueue_reviews", fake_reviews)

    final_list.handle_message({"kind": "screen", "platform_user_id": "user-1", "symbols": ["INFY"]})

    assert queued == ["INFY"]
    assert final_list.public_snapshot()["accepted"] == 1


def test_queue_takes_the_place_of_the_local_loop(monkeypatch):
    monkeypatch.setattr("kite_app.equity_queue.enqueue_equity_pass", lambda user, delay_seconds=0, wave=0: True)

    def boom(*args, **kwargs):
        raise AssertionError("local loop")

    monkeypatch.setattr(final_list.threading, "Thread", boom)

    final_list._launch({"api_key": "key", "access_token": "secret-token", "platform_user_id": "user-1"})
    snapshot = final_list.public_snapshot()

    assert snapshot["working"] is True
    assert "secret-token" not in str(snapshot)
    assert any("Queued" in line["text"] for line in snapshot["activity"])
