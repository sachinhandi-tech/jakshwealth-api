"""LLM service factory."""

from __future__ import annotations

import os

from services.llm.base import LlmService
from services.llm.mock_service import MockLlmService
from services.llm.remote_service import RemoteLlmService

_VALID_PROVIDERS = frozenset({"mock", "remote"})


def llm_service_name() -> str:
    configured = (os.environ.get("JW_LLM_SERVICE") or "mock").strip().lower()
    return configured if configured in _VALID_PROVIDERS else "mock"


def get_llm_service(name: str | None = None) -> LlmService:
    provider = (name or llm_service_name()).strip().lower()
    if provider == "remote":
        return RemoteLlmService()
    return MockLlmService()
