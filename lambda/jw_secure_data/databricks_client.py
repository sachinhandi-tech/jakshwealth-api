"""Databricks SQL warehouse access for ``jw_secure_data``."""

from __future__ import annotations

import threading
from typing import Any

import config
from jw_log import ExternalServiceError, call_external

_HTTP_PATH_TEMPLATE = "/sql/1.0/warehouses/{warehouse_id}"
_thread_local = threading.local()


def _sql_module():
    from databricks import sql

    return sql


def is_configured() -> bool:
    settings = config.databricks_settings()
    return all(settings[key] for key in ("server_hostname", "warehouse_id", "access_token"))


def _connect_kwargs(settings: dict) -> dict:
    if settings.get("tls_no_verify"):
        return {"_tls_no_verify": True}
    ca_file = settings.get("tls_trusted_ca_file")
    if ca_file:
        return {"_tls_trusted_ca_file": ca_file}
    return {}


def _connection_settings() -> dict[str, str]:
    settings = config.databricks_settings()
    missing = [
        key
        for key in ("server_hostname", "warehouse_id", "access_token")
        if not settings[key]
    ]
    if missing:
        raise ExternalServiceError(
            dep="databricks",
            op="Connect",
            message="Databricks is not configured; missing: " + ", ".join(sorted(missing)),
            reason="missing_config",
            hint="Set DATABRICKS_SERVER_HOSTNAME, DATABRICKS_WAREHOUSE_ID, and DATABRICKS_ACCESS_TOKEN.",
        )
    return settings


def _open_connection(settings: dict):
    sql = _sql_module()
    return sql.connect(
        server_hostname=settings["server_hostname"],
        http_path=_HTTP_PATH_TEMPLATE.format(warehouse_id=settings["warehouse_id"]),
        access_token=settings["access_token"],
        **_connect_kwargs(settings),
    )


def _get_thread_connection(settings: dict):
    connection = getattr(_thread_local, "connection", None)
    connection_key = getattr(_thread_local, "connection_key", None)
    settings_key = (
        settings["server_hostname"],
        settings["warehouse_id"],
        settings["access_token"],
        settings.get("tls_no_verify"),
        settings.get("tls_trusted_ca_file"),
    )
    if connection is not None and connection_key == settings_key:
        return connection

    if connection is not None:
        try:
            connection.close()
        except Exception:
            pass

    connection = _open_connection(settings)
    _thread_local.connection = connection
    _thread_local.connection_key = settings_key
    return connection


def _reset_thread_connection() -> None:
    connection = getattr(_thread_local, "connection", None)
    _thread_local.connection = None
    _thread_local.connection_key = None
    if connection is not None:
        try:
            connection.close()
        except Exception:
            pass


def _execute_query(connection, query: str, params: list[Any] | tuple[Any, ...] | None) -> list[dict]:
    with connection.cursor() as cursor:
        if params:
            cursor.execute(query, tuple(params))
        else:
            cursor.execute(query)
        columns = [column[0] for column in (cursor.description or [])]
        if not columns:
            return []
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_rows(query: str, params: list[Any] | tuple[Any, ...] | None = None) -> list[dict]:
    settings = _connection_settings()
    hostname = settings["server_hostname"]

    def _query():
        try:
            connection = _get_thread_connection(settings)
            return _execute_query(connection, query, params)
        except Exception:
            _reset_thread_connection()
            connection = _get_thread_connection(settings)
            return _execute_query(connection, query, params)

    return call_external(
        "databricks",
        "SQL.Query",
        _query,
        host=hostname,
        warehouse=settings["warehouse_id"],
        sql=query[:200],
        paramCount=len(params or ()),
    )


def fetch_rows_with_params(query: str, params: list[Any] | tuple[Any, ...]) -> list[dict]:
    """Execute a parameterized warehouse query."""
    return fetch_rows(query, params=params)


def warm_connection() -> None:
    """Open or reuse the thread-local warehouse connection before the first query."""
    settings = config.databricks_settings()
    if not all(settings[key] for key in ("server_hostname", "warehouse_id", "access_token")):
        return
    call_external(
        "databricks",
        "SQL.Connect",
        lambda: _get_thread_connection(settings),
        host=settings["server_hostname"],
        warehouse=settings["warehouse_id"],
    )


def fetch_secure_data() -> list[dict]:
    return fetch_rows("SELECT * FROM range(10)")
