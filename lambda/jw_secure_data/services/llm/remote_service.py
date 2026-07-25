"""Future remote LLM integration point."""

from __future__ import annotations

import json
from typing import Any
from urllib import error, request

import config
from services.llm.types import LlmChatRequest, LlmChatResponse, LlmQueryPlan

_PROVIDER = "remote"


class RemoteLlmService:
    """
    HTTP-backed LLM provider.

    Configure with:
    - ``JW_LLM_ENDPOINT``: POST target that accepts the chat request JSON body
    - ``JW_LLM_API_KEY`` (optional): bearer token for the upstream service
    - ``JW_LLM_MODEL`` (optional): model name recorded in responses
    """

    provider_name = _PROVIDER

    def __init__(
        self,
        *,
        endpoint: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        settings = config.llm_settings()
        self._endpoint = (endpoint or settings["endpoint"]).strip()
        self._api_key = (api_key or settings["api_key"]).strip()
        self._model = (model or settings["model"]).strip()
        self._timeout_seconds = (
            timeout_seconds if timeout_seconds is not None else settings["timeout_seconds"]
        )

    def complete(self, request_payload: LlmChatRequest) -> LlmChatResponse:
        if not self._endpoint:
            raise RuntimeError(
                "Remote LLM is not configured. Set JW_LLM_ENDPOINT or use JW_LLM_SERVICE=mock."
            )

        body = {
            "prompt": request_payload.prompt,
            "context": {
                "datamap": request_payload.context.datamap,
                "dsl_examples": request_payload.context.dsl_examples,
                "response_templates": request_payload.context.response_templates,
            },
        }
        raw = self._post_json(self._endpoint, body)
        return self._parse_response(raw)

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        encoded = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        req = request.Request(url, data=encoded, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Remote LLM request failed ({exc.code}): {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Remote LLM request failed: {exc}") from exc

    def _parse_response(self, payload: dict[str, Any]) -> LlmChatResponse:
        plan_payload = payload.get("plan") if isinstance(payload.get("plan"), dict) else payload
        response_type = str(plan_payload.get("response_type") or plan_payload.get("responseType"))
        if response_type not in {"text", "table", "chart"}:
            raise RuntimeError("Remote LLM response missing a valid response_type")

        plan = LlmQueryPlan(
            response_type=response_type,  # type: ignore[arg-type]
            text=plan_payload.get("text") or plan_payload.get("content"),
            dsl=plan_payload.get("dsl"),
            presentation=plan_payload.get("presentation"),
            sample_rows=plan_payload.get("sample_rows"),
        )
        model = str(payload.get("model") or self._model)
        provider = str(payload.get("provider") or self.provider_name)
        return LlmChatResponse(plan=plan, provider=provider, model=model)
