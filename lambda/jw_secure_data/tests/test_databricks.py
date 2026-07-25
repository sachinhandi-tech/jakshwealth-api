from unittest.mock import MagicMock, patch

import pytest

import databricks_client

_EXAMPLE_HOST = "example.cloud.databricks.com"
_EXAMPLE_WAREHOUSE_ID = "warehouse-example-id"


def _connection(cursor):
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    return connection


@pytest.fixture(autouse=True)
def _reset_databricks_thread_connection():
    databricks_client._reset_thread_connection()
    yield
    databricks_client._reset_thread_connection()


@patch.object(databricks_client.config, "databricks_settings")
@patch.object(databricks_client, "call_external", side_effect=lambda _dep, _op, fn, **_kw: fn())
@patch.object(databricks_client, "_sql_module")
def test_fetch_rows_returns_dicts(mock_sql_module, _call_external, mock_settings):
    mock_settings.return_value = {
        "server_hostname": _EXAMPLE_HOST,
        "warehouse_id": _EXAMPLE_WAREHOUSE_ID,
        "access_token": "token-value",
        "tls_trusted_ca_file": "",
        "tls_no_verify": False,
    }

    cursor = MagicMock()
    cursor.description = [("id",), ("name",)]
    cursor.fetchall.return_value = [(0, "a"), (1, "b")]
    sql = MagicMock()
    sql.connect.return_value = _connection(cursor)
    mock_sql_module.return_value = sql

    rows = databricks_client.fetch_rows("SELECT * FROM range(2)")

    sql.connect.assert_called_once_with(
        server_hostname=_EXAMPLE_HOST,
        http_path=f"/sql/1.0/warehouses/{_EXAMPLE_WAREHOUSE_ID}",
        access_token="token-value",
    )
    cursor.execute.assert_called_once_with("SELECT * FROM range(2)")
    assert rows == [{"id": 0, "name": "a"}, {"id": 1, "name": "b"}]


@patch.object(databricks_client.config, "databricks_settings")
@patch.object(databricks_client, "call_external", side_effect=lambda _dep, _op, fn, **_kw: fn())
@patch.object(databricks_client, "_sql_module")
def test_fetch_rows_passes_query_parameters(mock_sql_module, _call_external, mock_settings):
    mock_settings.return_value = {
        "server_hostname": _EXAMPLE_HOST,
        "warehouse_id": _EXAMPLE_WAREHOUSE_ID,
        "access_token": "token-value",
        "tls_trusted_ca_file": "",
        "tls_no_verify": False,
    }

    cursor = MagicMock()
    cursor.description = [("region",), ("claim_count",)]
    cursor.fetchall.return_value = [("North", 10)]
    sql = MagicMock()
    sql.connect.return_value = _connection(cursor)
    mock_sql_module.return_value = sql

    rows = databricks_client.fetch_rows_with_params(
        "SELECT region, claim_count FROM claim_fact WHERE claim_status = ?",
        ["PAID"],
    )

    cursor.execute.assert_called_once_with(
        "SELECT region, claim_count FROM claim_fact WHERE claim_status = ?",
        ("PAID",),
    )
    assert rows == [{"region": "North", "claim_count": 10}]


@patch.object(databricks_client.config, "databricks_settings")
@patch.object(databricks_client, "call_external", side_effect=lambda _dep, _op, fn, **_kw: fn())
@patch.object(databricks_client, "_sql_module")
def test_fetch_rows_passes_tls_options_for_deployed_env(mock_sql_module, _call_external, mock_settings):
    mock_settings.return_value = {
        "server_hostname": "host.example.com",
        "warehouse_id": "wh-1",
        "access_token": "token",
        "tls_trusted_ca_file": "/var/task/certs/corp-ca.pem",
        "tls_no_verify": False,
    }
    cursor = MagicMock()
    cursor.description = []
    cursor.fetchall.return_value = []
    sql = MagicMock()
    sql.connect.return_value = _connection(cursor)
    mock_sql_module.return_value = sql

    databricks_client.fetch_rows("SELECT 1")

    sql.connect.assert_called_once_with(
        server_hostname="host.example.com",
        http_path="/sql/1.0/warehouses/wh-1",
        access_token="token",
        _tls_trusted_ca_file="/var/task/certs/corp-ca.pem",
    )


@patch.object(databricks_client.config, "databricks_settings")
@patch.object(databricks_client, "call_external", side_effect=lambda _dep, _op, fn, **_kw: fn())
@patch.object(databricks_client, "_sql_module")
def test_fetch_rows_skips_tls_verify_for_local(mock_sql_module, _call_external, mock_settings):
    mock_settings.return_value = {
        "server_hostname": "host.example.com",
        "warehouse_id": "wh-1",
        "access_token": "token",
        "tls_trusted_ca_file": "",
        "tls_no_verify": True,
    }
    cursor = MagicMock()
    cursor.description = []
    cursor.fetchall.return_value = []
    sql = MagicMock()
    sql.connect.return_value = _connection(cursor)
    mock_sql_module.return_value = sql

    databricks_client.fetch_rows("SELECT 1")

    sql.connect.assert_called_once_with(
        server_hostname="host.example.com",
        http_path="/sql/1.0/warehouses/wh-1",
        access_token="token",
        _tls_no_verify=True,
    )


@patch.object(databricks_client, "fetch_rows")
def test_fetch_secure_data_uses_range_query(mock_fetch_rows):
    mock_fetch_rows.return_value = [{"id": 0}]
    assert databricks_client.fetch_secure_data() == [{"id": 0}]
    mock_fetch_rows.assert_called_once_with("SELECT * FROM range(10)")
