import json
import os

import config


def test_secret_name_for_each_environment():
    assert config.secret_name("dev") == "dev/jakshwealth/config"
    assert config.secret_name("test") == "test/jakshwealth/config"
    assert config.secret_name("prod") == "prod/jakshwealth/config"
    # local development is backed by the dev secret.
    assert config.secret_name("local") == "dev/jakshwealth/config"


def test_local_override_file_wins_over_secret(tmp_path, monkeypatch):
    override = tmp_path / "config.local.json"
    override.write_text(json.dumps({"OKTA_URL": "https://override.example", "NEW_KEY": "1"}))

    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("CONFIG_SKIP_AWS", "true")
    monkeypatch.setenv("LOCAL_CONFIG_FILE", str(override))
    monkeypatch.delenv("OKTA_URL", raising=False)
    monkeypatch.delenv("NEW_KEY", raising=False)

    config.load_config(force=True)

    assert os.environ["OKTA_URL"] == "https://override.example"
    assert os.environ["NEW_KEY"] == "1"


def test_placeholder_local_override_does_not_replace_secret(tmp_path, monkeypatch):
    override = tmp_path / "config.local.json"
    override.write_text(
        json.dumps({"OKTA_CLIENT_SECRET": "replace-with-okta-client-secret", "FRONTEND_URL": "http://localhost:4200"})
    )

    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("CONFIG_SKIP_AWS", "true")
    monkeypatch.setenv("LOCAL_CONFIG_FILE", str(override))
    monkeypatch.setenv("OKTA_CLIENT_SECRET", "mock-secret-from-aws")
    monkeypatch.delenv("FRONTEND_URL", raising=False)

    config.load_config(force=True)

    assert os.environ["OKTA_CLIENT_SECRET"] == "mock-secret-from-aws"
    assert os.environ["FRONTEND_URL"] == "http://localhost:4200"


def test_user_gg_maps_to_required_groups(tmp_path, monkeypatch):
    override = tmp_path / "config.local.json"
    override.write_text(json.dumps({"USER_GG": "TEST_USER_GROUP"}))

    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("CONFIG_SKIP_AWS", "true")
    monkeypatch.setenv("LOCAL_CONFIG_FILE", str(override))
    monkeypatch.delenv("JW_REQUIRED_GROUPS", raising=False)

    config.load_config(force=True)

    assert os.environ["JW_REQUIRED_GROUPS"] == "TEST_USER_GROUP"


def test_user_and_admin_gg_map_to_required_groups(tmp_path, monkeypatch):
    override = tmp_path / "config.local.json"
    override.write_text(
        json.dumps({
            "USER_GG": "TEST_USER_GROUP",
            "ADMIN_GG": "TEST_ADMIN_GROUP",
        })
    )

    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("CONFIG_SKIP_AWS", "true")
    monkeypatch.setenv("LOCAL_CONFIG_FILE", str(override))
    monkeypatch.delenv("JW_REQUIRED_GROUPS", raising=False)

    config.load_config(force=True)

    assert os.environ["JW_REQUIRED_GROUPS"] == (
        "TEST_USER_GROUP,TEST_ADMIN_GROUP"
    )
    assert config.required_global_groups() == [
        "TEST_USER_GROUP",
        "TEST_ADMIN_GROUP",
    ]


def test_invalid_environment_raises(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("CONFIG_SKIP_AWS", "true")
    try:
        config.load_config(force=True)
    except ValueError as exc:
        assert "staging" in str(exc)
    else:
        raise AssertionError("expected ValueError for invalid environment")
