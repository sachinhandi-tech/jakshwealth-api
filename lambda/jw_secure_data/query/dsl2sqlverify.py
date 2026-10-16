"""Verify LLM-composed DSL against the datamap before SQL compilation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from query.dsl_compiler import DSLValidationError, compile_json_dsl
from query.datamap import column_names, compiler_metadata, query_dialect, table_names

JSON = dict[str, Any]

_MAX_LIMIT = 10_000
_DEFAULT_REQUIRED_LIMIT = 1_000


@dataclass(frozen=True)
class DSLVerificationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    compiled_sql: str | None = None
    compiled_params: list[Any] | None = None


class DSLVerificationError(ValueError):
    """Raised when DSL verification fails."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        message = "; ".join(errors) if errors else "DSL verification failed"
        super().__init__(message)


def verify_dsl(
    dsl: JSON,
    datamap: JSON,
    *,
    require_limit: bool = True,
    max_limit: int = _DEFAULT_REQUIRED_LIMIT,
    compile_check: bool = True,
) -> DSLVerificationResult:
    """
    Validate a DSL document against the datamap and optionally compile it.

  Checks performed before compilation:
  - root shape and required clauses
  - referenced tables/columns exist in the datamap
  - limit policy for interactive chat queries

  When ``compile_check`` is true, the DSL is passed to ``query.dsl_compiler`` using
    datamap-derived metadata so syntax and alias rules are enforced.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(dsl, dict):
        return DSLVerificationResult(valid=False, errors=["DSL root must be a JSON object"])

    known_tables = table_names(datamap)
    if not known_tables:
        errors.append("Datamap does not define any tables")

    from_obj = dsl.get("from")
    if not isinstance(from_obj, dict):
        errors.append("'from' must be an object with 'table' and 'alias'")
        from_table = None
    else:
        from_table = from_obj.get("table")
        from_alias = from_obj.get("alias")
        if not isinstance(from_table, str) or not from_table:
            errors.append("from.table must be a non-empty string")
        elif from_table not in known_tables:
            errors.append(f"Unknown from.table {from_table!r} (not in datamap)")
        if not isinstance(from_alias, str) or not from_alias:
            errors.append("from.alias must be a non-empty string")

    select_items = dsl.get("select")
    if not isinstance(select_items, list) or not select_items:
        errors.append("select must be a non-empty list")

    joins = dsl.get("joins", [])
    if joins is not None and not isinstance(joins, list):
        errors.append("joins must be a list when provided")
    elif isinstance(joins, list):
        for index, join in enumerate(joins):
            if not isinstance(join, dict):
                errors.append(f"joins[{index}] must be an object")
                continue
            join_table = join.get("table")
            if not isinstance(join_table, str) or join_table not in known_tables:
                errors.append(f"joins[{index}].table {join_table!r} is not in datamap")

    limit = dsl.get("limit")
    if require_limit and limit is None:
        errors.append("limit is required for AI chat queries")
    elif limit is not None:
        if not isinstance(limit, int) or limit < 0:
            errors.append("limit must be a non-negative integer")
        elif limit > max_limit:
            errors.append(f"limit must be <= {max_limit}")
        elif limit > _MAX_LIMIT:
            errors.append(f"limit must be <= {_MAX_LIMIT}")

    if errors:
        return DSLVerificationResult(valid=False, errors=errors, warnings=warnings)

    _collect_field_reference_errors(dsl, datamap, errors)

    if errors:
        return DSLVerificationResult(valid=False, errors=errors, warnings=warnings)

    compiled_sql = None
    compiled_params = None
    if compile_check:
        try:
            compiled = compile_json_dsl(
                dsl,
                dialect=query_dialect(datamap),
                metadata=compiler_metadata(datamap),
            )
            compiled_sql = compiled.sql
            compiled_params = list(compiled.params)
        except DSLValidationError as exc:
            errors.append(str(exc))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:  # pragma: no cover - defensive
            errors.append(f"DSL compilation failed: {exc}")

    return DSLVerificationResult(
        valid=not errors,
        errors=errors,
        warnings=warnings,
        compiled_sql=compiled_sql,
        compiled_params=compiled_params,
    )


def assert_valid_dsl(dsl: JSON, datamap: JSON, **kwargs: Any) -> DSLVerificationResult:
    """Verify DSL and raise ``DSLVerificationError`` when invalid."""
    result = verify_dsl(dsl, datamap, **kwargs)
    if not result.valid:
        raise DSLVerificationError(result.errors)
    return result


def _collect_field_reference_errors(dsl: JSON, datamap: JSON, errors: list[str]) -> None:
    aliases = _collect_aliases(dsl)
    for ref in _iter_field_references(dsl):
        alias, column = _split_field_ref(ref)
        if alias is None:
            continue
        table = aliases.get(alias)
        if table is None:
            errors.append(f"Field reference {ref!r} uses unknown alias {alias!r}")
            continue
        if column not in column_names(datamap, table):
            errors.append(f"Field reference {ref!r} is not defined in datamap")


def _collect_aliases(dsl: JSON) -> dict[str, str]:
    aliases: dict[str, str] = {}
    from_obj = dsl.get("from")
    if isinstance(from_obj, dict):
        table = from_obj.get("table")
        alias = from_obj.get("alias")
        if isinstance(table, str) and isinstance(alias, str):
            aliases[alias] = table
    joins = dsl.get("joins") or []
    if isinstance(joins, list):
        for join in joins:
            if not isinstance(join, dict):
                continue
            table = join.get("table")
            alias = join.get("alias")
            if isinstance(table, str) and isinstance(alias, str):
                aliases[alias] = table
    return aliases


def _split_field_ref(ref: str) -> tuple[str | None, str]:
    if "." not in ref:
        return None, ref
    alias, column = ref.split(".", 1)
    return alias, column


def _iter_field_references(node: Any) -> list[str]:
    refs: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if isinstance(value.get("field"), str):
                refs.append(value["field"])
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(node)
    return refs
