"""Resolve chart SQL builders via nested registry and stable chart_id."""

from __future__ import annotations

from collections.abc import Callable

from features.fetch_charts.models import DEFAULT_DASHBOARD, ChartQueryContext
from features.fetch_charts.query_library.chart_registry import CHART_REGISTRY

QueryBuilder = Callable[[ChartQueryContext], str]
BuilderKey = tuple[str, str]  # (chart_id, timeline)


def resolve_chart_id(context: ChartQueryContext) -> str | None:
    """Resolve stable chart_id — prefer metadata id, else nested registry path."""
    if context.chart_id:
        return context.chart_id.strip()

    dashboard = (context.dashboard or DEFAULT_DASHBOARD).strip() or DEFAULT_DASHBOARD
    designation = context.designation.lower().strip()
    view = context.view.strip()
    timeline = context.timeline.lower().strip()
    chart_name = context.chart_name.strip()

    try:
        return CHART_REGISTRY[dashboard][designation][view][timeline][chart_name]
    except KeyError:
        return None


def builder_key(context: ChartQueryContext) -> BuilderKey | None:
    chart_id = resolve_chart_id(context)
    if not chart_id:
        return None
    return chart_id, context.timeline.lower().strip()


def resolve_query_builder(
    context: ChartQueryContext,
    builders: dict[BuilderKey, QueryBuilder],
    default: QueryBuilder,
) -> QueryBuilder:
    key = builder_key(context)
    if key is None:
        return default
    return builders.get(key, default)
