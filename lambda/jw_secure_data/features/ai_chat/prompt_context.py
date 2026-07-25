"""Load prompt assets used by the LLM service."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from query.datamap import load_datamap
from services.llm.types import LlmPromptContext

_ASSETS_DIR = Path(__file__).resolve().parent / "prompt_assets"


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


@lru_cache(maxsize=1)
def load_dsl_examples() -> list[dict[str, Any]]:
    payload = _read_json(_ASSETS_DIR / "dsl_examples.json")
    if not isinstance(payload, list):
        raise ValueError("dsl_examples.json must be a JSON array")
    return payload


@lru_cache(maxsize=1)
def load_response_templates() -> dict[str, Any]:
    payload = _read_json(_ASSETS_DIR / "response_templates.json")
    if not isinstance(payload, dict):
        raise ValueError("response_templates.json must be a JSON object")
    return payload


def build_prompt_context(datamap: dict[str, Any] | None = None) -> LlmPromptContext:
    return LlmPromptContext(
        datamap=datamap or load_datamap(),
        dsl_examples=load_dsl_examples(),
        response_templates=load_response_templates(),
    )
