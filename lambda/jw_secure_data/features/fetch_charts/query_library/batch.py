"""Combine per-chart SQL into a single warehouse round-trip."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from features.fetch_charts.models import ChartQueryContext
from features.fetch_charts.query_library.builder import build_chart_query
from features.fetch_charts.query_library.queries import _default_query

_TRAILING_ORDER_BY = re.compile(r"\s+ORDER\s+BY\s+.+$", re.IGNORECASE | re.DOTALL)


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def strip_trailing_order_by(query: str) -> str:
    return _TRAILING_ORDER_BY.sub("", query.strip())


def _wrap_chart_subquery(chart_id: str, query: str) -> str:
    inner = strip_trailing_order_by(query)
    safe_alias = chart_id.replace("-", "_").replace(".", "_")
    return (
        f"SELECT {_sql_literal(chart_id)} AS chart_id, "
        "sort_order, row_kind, label, data_value, series_index, center_line, hover_message "
        f"FROM ({inner}) AS chart_{safe_alias}"
    )


def build_batch_chart_query(
    contexts: list[ChartQueryContext],
    *,
    use_default: bool = False,
) -> str:
    if not contexts:
        raise ValueError("At least one chart context is required")

    parts = []
    for context in contexts:
        query = _default_query(context) if use_default else build_chart_query(context)
        parts.append(_wrap_chart_subquery(context.chart_id, query))

    return (
        "\nUNION ALL\n".join(parts)
        + "\nORDER BY chart_id, row_kind DESC, sort_order, series_index"
    )


def split_batch_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        chart_id = row.get("chart_id")
        if chart_id is None:
            chart_id = row.get("CHART_ID")
        if chart_id is None:
            continue
        chart_key = str(chart_id)
        grouped[chart_key].append(
            {key: value for key, value in row.items() if key.lower() != "chart_id"}
        )
    return dict(grouped)
