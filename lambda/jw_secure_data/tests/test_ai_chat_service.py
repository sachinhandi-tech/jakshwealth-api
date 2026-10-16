from features.ai_chat import service


def test_process_chat_prompt_returns_text_response():
    body = service.process_chat_prompt("hello")
    assert body["responseType"] == "text"
    assert body["content"]
    assert body["meta"]["llmProvider"] == "mock"


def test_process_chat_prompt_returns_verified_table_response():
    body = service.process_chat_prompt("list recent claims")
    assert body["responseType"] == "table"
    assert body["columns"]
    assert body["rows"]
    assert "claim_fact" in body["meta"]["sql"]


def test_process_chat_prompt_returns_verified_chart_response():
    body = service.process_chat_prompt("show doughnut of claims by region")
    assert body["responseType"] == "chart"
    assert body["chartType"] == "doughnut"
    assert body["labels"] == ["North", "South", "East"]
    assert body["data"] == [420, 360, 295]
    assert body["centerLines"]


def test_process_chat_prompt_rejects_empty_prompt():
    try:
        service.process_chat_prompt("   ")
    except service.ChatProcessingError:
        return
    raise AssertionError("expected ChatProcessingError")
