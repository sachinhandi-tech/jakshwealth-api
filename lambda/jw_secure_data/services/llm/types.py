"""Shared LLM request/response contracts for AI chat."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ResponseType = Literal["text", "table", "chart"]
ChartType = Literal["bar", "doughnut", "pie"]

JSON = dict[str, Any]


@dataclass(frozen=True)
class LlmPromptContext:
    """Context bundled with each prompt for the LLM provider."""

    datamap: JSON
    dsl_examples: list[JSON] = field(default_factory=list)
    response_templates: JSON = field(default_factory=dict)


@dataclass(frozen=True)
class LlmChatRequest:
    prompt: str
    context: LlmPromptContext


@dataclass(frozen=True)
class LlmQueryPlan:
    """Structured plan returned by an LLM provider before warehouse execution."""

    response_type: ResponseType
    text: str | None = None
    dsl: JSON | None = None
    presentation: JSON | None = None
    sample_rows: list[JSON] | None = None


@dataclass(frozen=True)
class LlmChatResponse:
    plan: LlmQueryPlan
    provider: str
    model: str
