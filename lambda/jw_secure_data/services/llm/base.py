"""LLM provider abstraction for AI chat."""

from __future__ import annotations

from typing import Protocol

from services.llm.types import LlmChatRequest, LlmChatResponse


class LlmService(Protocol):
    """Provider contract used by the AI chat feature."""

    provider_name: str

    def complete(self, request: LlmChatRequest) -> LlmChatResponse:
        """Turn a user prompt plus prompt context into a structured query plan."""
