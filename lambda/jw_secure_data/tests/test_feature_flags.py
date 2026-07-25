import json
from pathlib import Path

import feature_flags


def test_default_flags_disable_ai_chat():
    flags = feature_flags.default_feature_flags()
    assert flags["aiChat"] is False
    assert flags["proofPoints"] is True


def test_platform_gate_forces_ai_chat_off(tmp_path, monkeypatch):
    override_file = tmp_path / "feature_flags.local.json"
    override_file.write_text(json.dumps({"aiChat": True}), encoding="utf-8")
    monkeypatch.setenv("FEATURE_FLAGS_OVERRIDE_FILE", str(override_file))
    monkeypatch.delenv("ENABLE_AI_CHAT", raising=False)

    assert feature_flags.is_ai_chat_platform_enabled() is False
    assert feature_flags.load_feature_flags()["aiChat"] is False
    assert feature_flags.is_feature_enabled("aiChat") is False


def test_platform_gate_allows_admin_override_when_enabled(tmp_path, monkeypatch):
    override_file = tmp_path / "feature_flags.local.json"
    monkeypatch.setenv("FEATURE_FLAGS_OVERRIDE_FILE", str(override_file))
    monkeypatch.setenv("ENABLE_AI_CHAT", "true")

    updated = feature_flags.update_feature_flags({"aiChat": True})
    assert updated["aiChat"] is True
    assert feature_flags.is_feature_enabled("aiChat") is True


def test_update_ai_chat_rejected_when_platform_disabled(tmp_path, monkeypatch):
    override_file = tmp_path / "feature_flags.local.json"
    monkeypatch.setenv("FEATURE_FLAGS_OVERRIDE_FILE", str(override_file))
    monkeypatch.delenv("ENABLE_AI_CHAT", raising=False)

    try:
        feature_flags.update_feature_flags({"aiChat": True})
    except ValueError as exc:
        assert "ENABLE_AI_CHAT" in str(exc)
    else:
        raise AssertionError("expected ValueError")
