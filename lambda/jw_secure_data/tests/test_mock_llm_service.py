from features.ai_chat.prompt_context import build_prompt_context
from services.llm.mock_service import MockLlmService
from services.llm.types import LlmChatRequest


def test_mock_llm_service_returns_text_plan_for_help_prompt():
    context = build_prompt_context()
    response = MockLlmService().complete(LlmChatRequest(prompt="hello", context=context))
    assert response.provider == "mock"
    assert response.plan.response_type == "text"
    assert response.plan.text


def test_mock_llm_service_returns_table_plan_for_list_prompt():
    context = build_prompt_context()
    response = MockLlmService().complete(
        LlmChatRequest(prompt="show a table of recent claims", context=context)
    )
    assert response.plan.response_type == "table"
    assert response.plan.dsl
    assert response.plan.sample_rows


def test_mock_llm_service_returns_chart_plan_for_region_prompt():
    context = build_prompt_context()
    response = MockLlmService().complete(
        LlmChatRequest(prompt="chart claims by region", context=context)
    )
    assert response.plan.response_type == "chart"
    assert response.plan.presentation["chartType"] == "bar"
    assert response.plan.dsl
