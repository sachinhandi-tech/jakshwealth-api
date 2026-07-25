"""Shared feature-flag resolution for JakshWealth Lambdas."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_ENV_ENABLE_AI_CHAT = "ENABLE_AI_CHAT"
_TRUTHY = frozenset({"true", "1", "yes", "on"})

_DEFAULT_FLAGS: dict[str, bool] = {
    "stockAnalysis": True,
    "utilization": True,
    "proofPoints": True,
    "systemAdmin": True,
    "aiChat": False,
}


def default_feature_flags() -> dict[str, bool]:
    return dict(_DEFAULT_FLAGS)


def is_ai_chat_platform_enabled() -> bool:
    """
    Hard platform gate from AWS secret / environment.

    When false, AI chat stays disabled regardless of admin overrides.
    Set ENABLE_AI_CHAT=true in the JakshWealth secret (or config.local.json locally).
    """
    raw = (os.environ.get(_ENV_ENABLE_AI_CHAT) or "").strip().lower()
    return raw in _TRUTHY


def can_manage_ai_chat() -> bool:
    """Whether the admin UI may toggle AI chat for this deployment."""
    return is_ai_chat_platform_enabled()


def _parse_json_mapping(raw: str | None, label: str) -> dict[str, bool]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    normalized: dict[str, bool] = {}
    for key, value in payload.items():
        if isinstance(value, bool):
            normalized[str(key)] = value
    return normalized


def _base_flags_from_env() -> dict[str, bool]:
    return _parse_json_mapping(os.environ.get("JW_FEATURE_FLAGS"), "JW_FEATURE_FLAGS")


def _override_file_path() -> Path | None:
    configured = (os.environ.get("FEATURE_FLAGS_OVERRIDE_FILE") or "").strip()
    if configured:
        return Path(configured)
    return None


def _read_override_file() -> dict[str, bool]:
    path = _override_file_path()
    if path is None or not path.is_file():
        return {}
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    normalized: dict[str, bool] = {}
    for key, value in payload.items():
        if isinstance(value, bool):
            normalized[str(key)] = value
    return normalized


def _write_override_file(overrides: dict[str, bool]) -> None:
    path = _override_file_path()
    if path is None:
        raise RuntimeError(
            "FEATURE_FLAGS_OVERRIDE_FILE is not configured; feature toggles cannot be persisted"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(overrides, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _apply_ai_chat_platform_gate(flags: dict[str, bool]) -> dict[str, bool]:
    if not is_ai_chat_platform_enabled():
        flags["aiChat"] = False
    return flags


def load_feature_flags() -> dict[str, bool]:
    """Merge defaults, secret/env flags, and optional override file values."""
    flags = default_feature_flags()
    flags.update(_base_flags_from_env())
    flags.update(_read_override_file())
    return _apply_ai_chat_platform_gate(flags)


def update_feature_flags(updates: dict[str, Any]) -> dict[str, bool]:
    """Persist boolean feature updates and return the merged flag set."""
    normalized: dict[str, bool] = {}
    for key, value in updates.items():
        if isinstance(value, bool):
            normalized[str(key)] = value

    if not normalized:
        raise ValueError("No boolean feature updates were provided")

    if "aiChat" in normalized and not can_manage_ai_chat():
        raise ValueError(
            "AI chat cannot be configured because ENABLE_AI_CHAT is disabled for this environment"
        )

    current_overrides = _read_override_file()
    current_overrides.update(normalized)
    _write_override_file(current_overrides)
    return load_feature_flags()


def is_feature_enabled(name: str) -> bool:
    if name == "aiChat" and not is_ai_chat_platform_enabled():
        return False
    return bool(load_feature_flags().get(name, False))
