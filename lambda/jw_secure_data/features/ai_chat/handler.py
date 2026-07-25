"""AI chat secure-data feature."""

from __future__ import annotations

from typing import Any

import feature_flags
import responses
from features.ai_chat import service
from request_trace import RequestTrace
from routing import FeatureRoute, parse_json_body


def handle(event, trace: RequestTrace, authorizer: dict[str, Any], method: str) -> dict:
    del authorizer, method  # reserved for future role-aware prompt policies
    if not feature_flags.is_feature_enabled("aiChat"):
        return trace.complete(
            responses.bad_request("AI chat is disabled by administrator settings")
        )

    payload = parse_json_body(event)
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        return trace.complete(responses.bad_request("prompt is required"))

    use_live_data = bool(payload.get("useLiveData"))
    llm_service = payload.get("llmService")
    if llm_service is not None and not isinstance(llm_service, str):
        return trace.complete(responses.bad_request("llmService must be a string when provided"))

    try:
        body = service.process_chat_prompt(
            prompt,
            llm_service_name=llm_service,
            use_live_data=use_live_data,
        )
    except service.ChatProcessingError as exc:
        return trace.complete(responses.bad_request(str(exc)))
    except RuntimeError as exc:
        return trace.complete(responses.bad_request(str(exc)))

    return trace.complete(responses.ok(body))


ROUTE = FeatureRoute(path="ai-chat", methods=frozenset({"POST"}), handle=handle)
