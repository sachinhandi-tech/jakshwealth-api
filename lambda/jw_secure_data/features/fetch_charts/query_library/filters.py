"""Shared filter clause builder for chart SQL queries."""

from __future__ import annotations

from features.fetch_charts.models import FILTER_COLUMN_MAP, ChartQueryContext


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def build_filter_clause(filters: dict[str, list[str]]) -> str:
    """Return AND-prefixed WHERE fragments for active dashboard filters."""
    clauses: list[str] = []
    for api_key, column in FILTER_COLUMN_MAP.items():
        values = filters.get(api_key) or []
        if not values:
            continue
        quoted = ", ".join(_quote_literal(value) for value in values)
        clauses.append(f"{column} IN ({quoted})")
    if not clauses:
        return ""
    return " AND " + " AND ".join(clauses)


def build_filter_clause_for_context(context: ChartQueryContext) -> str:
    return build_filter_clause(context.filters)
