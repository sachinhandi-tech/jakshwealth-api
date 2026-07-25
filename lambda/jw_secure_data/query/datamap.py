"""Load and normalize the analytics datamap for LLM prompts and DSL validation."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_DATAMAP_PATH = Path(__file__).with_name("datamap.json")


def load_datamap(path: Path | None = None) -> dict[str, Any]:
    """Return the canonical datamap document."""
    target = path or _DATAMAP_PATH
    with target.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError("datamap root must be a JSON object")
    return payload


@lru_cache(maxsize=1)
def cached_datamap() -> dict[str, Any]:
    return load_datamap()


def table_names(datamap: dict[str, Any]) -> set[str]:
    tables = datamap.get("tables")
    if not isinstance(tables, dict):
        return set()
    return {str(name) for name in tables}


def column_names(datamap: dict[str, Any], table: str) -> set[str]:
    tables = datamap.get("tables")
    if not isinstance(tables, dict):
        return set()
    meta = tables.get(table)
    if not isinstance(meta, dict):
        return set()
    columns = meta.get("columns")
    if isinstance(columns, dict):
        return {str(name) for name in columns}
    if isinstance(columns, list):
        return {str(name) for name in columns}
    return set()


def compiler_metadata(datamap: dict[str, Any]) -> dict[str, Any]:
    """Shape expected by ``query.dsl_compiler.compile_json_dsl(..., metadata=...)``."""
    tables: dict[str, dict[str, list[str]]] = {}
    raw_tables = datamap.get("tables")
    if not isinstance(raw_tables, dict):
        return {"tables": tables}

    for table_name, table_meta in raw_tables.items():
        if not isinstance(table_meta, dict):
            continue
        columns = table_meta.get("columns")
        if isinstance(columns, dict):
            tables[str(table_name)] = {"columns": sorted(columns)}
        elif isinstance(columns, list):
            tables[str(table_name)] = {"columns": [str(column) for column in columns]}
    return {"tables": tables}


def query_dialect(datamap: dict[str, Any]) -> str:
    dialect = str(datamap.get("dialect") or "databricks").strip().lower()
    return dialect or "databricks"


def physical_table_name(datamap: dict[str, Any], logical_table: str) -> str:
    """Resolve a logical DSL table name to the warehouse table identifier."""
    tables = datamap.get("tables")
    if not isinstance(tables, dict):
        return logical_table
    meta = tables.get(logical_table)
    if not isinstance(meta, dict):
        return logical_table
    physical = meta.get("physical_table")
    if isinstance(physical, str) and physical.strip():
        return physical.strip()
    return logical_table


def resolve_physical_dsl(dsl: dict[str, Any], datamap: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``dsl`` with logical table names mapped to physical tables."""
    import copy

    resolved = copy.deepcopy(dsl)
    from_obj = resolved.get("from")
    if isinstance(from_obj, dict) and isinstance(from_obj.get("table"), str):
        from_obj["table"] = physical_table_name(datamap, from_obj["table"])

    joins = resolved.get("joins")
    if isinstance(joins, list):
        for join in joins:
            if isinstance(join, dict) and isinstance(join.get("table"), str):
                join["table"] = physical_table_name(datamap, join["table"])
    return resolved


def compiler_metadata_physical(datamap: dict[str, Any]) -> dict[str, Any]:
    """Metadata keyed by physical table names for compiled SQL validation."""
    tables: dict[str, dict[str, list[str]]] = {}
    raw_tables = datamap.get("tables")
    if not isinstance(raw_tables, dict):
        return {"tables": tables}

    for logical_name, table_meta in raw_tables.items():
        if not isinstance(table_meta, dict):
            continue
        columns = table_meta.get("columns")
        column_names_list: list[str] = []
        if isinstance(columns, dict):
            column_names_list = sorted(columns)
        elif isinstance(columns, list):
            column_names_list = [str(column) for column in columns]
        physical = physical_table_name(datamap, str(logical_name))
        tables[physical] = {"columns": column_names_list}
    return {"tables": tables}

