from services.llm.remote_service import RemoteLlmService


def test_remote_llm_service_requires_endpoint(monkeypatch):
    monkeypatch.delenv("JW_LLM_ENDPOINT", raising=False)
    service = RemoteLlmService(endpoint="")
    try:
        service.complete  # noqa: B018 - ensure method exists
        from features.ai_chat.prompt_context import build_prompt_context
        from services.llm.types import LlmChatRequest

        service.complete(LlmChatRequest(prompt="chart", context=build_prompt_context()))
    except RuntimeError as exc:
        assert "JW_LLM_ENDPOINT" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
