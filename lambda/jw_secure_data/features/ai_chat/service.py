"""AI chat orchestration: LLM plan -> DSL verify -> SQL compile -> response build."""

from __future__ import annotations

from typing import Any

import databricks_client
from query.dsl_compiler import compile_json_dsl
from features.ai_chat.prompt_context import build_prompt_context
from features.ai_chat.response_builder import build_chat_response
from query.datamap import (
    compiler_metadata_physical,
    load_datamap,
    query_dialect,
    resolve_physical_dsl,
)
from query.dsl2sqlverify import verify_dsl
from services.llm import get_llm_service
from services.llm.types import LlmChatRequest

JSON = dict[str, Any]


class ChatProcessingError(ValueError):
    """Raised when the chat pipeline cannot produce a response."""


def process_chat_prompt(
    prompt: str,
    *,
    llm_service_name: str | None = None,
    use_live_data: bool = False,
) -> JSON:
    """
    Execute the AI chat pipeline end-to-end.

    Returns a UI-ready payload with ``responseType`` of ``text``, ``table``, or
    ``chart``. When the LLM returns a DSL, it is verified and compiled before
    any warehouse access occurs.
    """
    cleaned_prompt = (prompt or "").strip()
    if not cleaned_prompt:
        raise ChatProcessingError("prompt is required")

    datamap = load_datamap()
    context = build_prompt_context(datamap)
    llm = get_llm_service(llm_service_name)
    llm_response = llm.complete(LlmChatRequest(prompt=cleaned_prompt, context=context))
    plan = llm_response.plan

    if plan.response_type == "text":
        return {
            "responseType": "text",
            "content": plan.text or "",
            "meta": _meta(llm_response.provider, llm_response.model),
        }

    if not plan.dsl:
        raise ChatProcessingError("LLM plan is missing DSL for a data-backed response")

    verification = verify_dsl(plan.dsl, datamap)
    if not verification.valid:
        raise ChatProcessingError(
            "DSL verification failed: " + "; ".join(verification.errors)
        )

    resolved_dsl = resolve_physical_dsl(plan.dsl, datamap)
    compiled = compile_json_dsl(
        resolved_dsl,
        dialect=query_dialect(datamap),
        metadata=compiler_metadata_physical(datamap),
    )
    rows = _resolve_rows(plan, compiled.sql, compiled.params, use_live_data=use_live_data)
    response = build_chat_response(plan, rows)
    response["meta"] = {
        **_meta(llm_response.provider, llm_response.model),
        "sql": compiled.sql,
        "paramCount": len(compiled.params),
        "verificationWarnings": verification.warnings,
    }
    return response


def _resolve_rows(
    plan,
    sql: str,
    params: list[Any],
    *,
    use_live_data: bool,
) -> list[JSON]:
    if use_live_data and databricks_client.is_configured():
        return databricks_client.fetch_rows_with_params(sql, params)

    if plan.sample_rows:
        return list(plan.sample_rows)
    return []


def _meta(provider: str, model: str) -> JSON:
    return {"llmProvider": provider, "llmModel": model}
