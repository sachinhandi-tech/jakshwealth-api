import os

import config

_EXAMPLE_HOST = "example.cloud.databricks.com"
_EXAMPLE_WAREHOUSE_ID = "warehouse-example-id"


def test_warehourse_id_alias_maps_to_warehouse_id(monkeypatch):
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)
    monkeypatch.setenv("DATABRICKS_WAREHOURSE_ID", _EXAMPLE_WAREHOUSE_ID)
    normalized = config._normalize_config({"DATABRICKS_WAREHOURSE_ID": _EXAMPLE_WAREHOUSE_ID})
    assert normalized["DATABRICKS_WAREHOUSE_ID"] == _EXAMPLE_WAREHOUSE_ID


def test_databricks_settings_reads_secret_keys(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("DATABRICKS_SERVER_HOSTNAME", _EXAMPLE_HOST)
    monkeypatch.setenv("DATABRICKS_WAREHOUSE_ID", _EXAMPLE_WAREHOUSE_ID)
    monkeypatch.setenv("DATABRICKS_ACCESS_TOKEN", "token-value")
    monkeypatch.delenv("DATABRICKS_TLS_TRUSTED_CA_FILE", raising=False)

    settings = config.databricks_settings()
    assert settings == {
        "server_hostname": _EXAMPLE_HOST,
        "warehouse_id": _EXAMPLE_WAREHOUSE_ID,
        "access_token": "token-value",
        "tls_trusted_ca_file": "",
        "tls_no_verify": False,
    }


def test_databricks_tls_no_verify_always_true_for_local(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("DATABRICKS_TLS_TRUSTED_CA_FILE", "/etc/ssl/corp-ca.pem")
    assert config.databricks_settings()["tls_no_verify"] is True


def test_load_config_reapplies_normalization_on_subsequent_call(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("CONFIG_SKIP_AWS", "true")
    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)
    monkeypatch.setenv("DATABRICKS_WAREHOURSE_ID", "wh-from-alias")

    config.load_config(force=True)
    assert os.environ["DATABRICKS_WAREHOUSE_ID"] == "wh-from-alias"

    monkeypatch.delenv("DATABRICKS_WAREHOUSE_ID", raising=False)
    config.load_config(force=False)
    assert os.environ.get("DATABRICKS_WAREHOUSE_ID") == "wh-from-alias"


def test_databricks_tls_uses_ca_file_in_deployed_env(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("DATABRICKS_TLS_TRUSTED_CA_FILE", "/var/task/certs/corp-ca.pem")
    settings = config.databricks_settings()
    assert settings["tls_no_verify"] is False
    assert settings["tls_trusted_ca_file"] == "/var/task/certs/corp-ca.pem"
