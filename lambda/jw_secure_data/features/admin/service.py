"""Admin area payload and feature-flag management."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import feature_flags


def build_admin_payload(authorizer: dict[str, Any]) -> dict[str, Any]:
    return {
        "message": "Admin area",
        "enableAiChat": feature_flags.can_manage_ai_chat(),
        "features": feature_flags.load_feature_flags(),
        "servedAt": datetime.now(timezone.utc).isoformat(),
    }


def update_features(payload: dict[str, Any]) -> dict[str, Any]:
    updates = payload.get("features") if isinstance(payload.get("features"), dict) else payload
    if not isinstance(updates, dict):
        raise ValueError("features must be an object")

    flags = feature_flags.update_feature_flags(updates)
    return {
        "message": "Feature flags updated",
        "enableAiChat": feature_flags.can_manage_ai_chat(),
        "features": flags,
        "servedAt": datetime.now(timezone.utc).isoformat(),
    }
