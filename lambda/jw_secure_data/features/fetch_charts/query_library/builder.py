"""Resolve chart SQL from the single queries module."""

from __future__ import annotations

from features.fetch_charts.models import ChartQueryContext
from features.fetch_charts.query_library import queries


def build_chart_query(context: ChartQueryContext) -> str:
    """Return the SQL query for a chart identified by dashboard/tier/view/timeline/name."""
    return queries.build_query(context)
