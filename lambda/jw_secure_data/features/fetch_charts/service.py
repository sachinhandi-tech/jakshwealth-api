"""Build proof point chart payloads from Databricks metadata and query library."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
from typing import Any

import databricks_client
from features.fetch_charts.metadata import resolve_chart_metadata
from features.fetch_charts.models import (
    DEFAULT_DASHBOARD,
    ChartMetadata,
    ChartQueryContext,
    normalize_filters,
)
from features.fetch_charts.query_library import build_chart_query
from features.fetch_charts.query_library.batch import build_batch_chart_query, split_batch_rows
from features.fetch_charts.query_library.queries import _default_query
from features.fetch_charts.result_parser import parse_chart_rows
from features.fetch_charts.view_catalog import catalog_metadata_rows

_CHART_TYPES = frozenset({"bar", "doughnut"})
_MAX_PARALLEL_CHART_QUERIES = 8
_CHART_EXECUTOR = ThreadPoolExecutor(max_workers=_MAX_PARALLEL_CHART_QUERIES)


def _chart_query_workers(chart_count: int) -> int:
    if chart_count <= 1:
        return 1
    return min(chart_count, _MAX_PARALLEL_CHART_QUERIES)


def _format_compact(value: int) -> str:
    absolute = abs(int(value))
    if absolute >= 1_000_000:
        millions = absolute / 1_000_000
        return f"{int(millions)}M" if millions.is_integer() else f"{millions:.1f}M"
    if absolute >= 1_000:
        thousands = absolute / 1_000
        return f"{int(thousands)}K" if thousands.is_integer() else f"{thousands:.1f}K"
    return f"{absolute:,}"


def _provider_group_doughnut(designation: str, filters: dict[str, Any]) -> dict[str, Any]:
    filter_count = sum(len(values) for values in filters.values() if isinstance(values, list))
    ccd_value = 160_000 + (filter_count * 1_000)
    non_ccd_value = 40_000 + (filter_count * 500)
    total = ccd_value + non_ccd_value
    return _doughnut_chart_payload(
        chart_id=f"{designation}-volume-provider-groups",
        title="Provider Group Volume",
        explanation="Chart explanation goes here",
        labels=["CCD", "Non CCD"],
        data=[ccd_value, non_ccd_value],
        center_lines=[
            _format_compact(ccd_value),
            "received CCD",
            f"out of {_format_compact(total)}",
        ],
        hover_messages=[
            f"CCD provider groups\nreceived {ccd_value:,} claims",
            f"Non CCD provider groups\nreceived {non_ccd_value:,} claims",
        ],
    )


def _provider_volume_doughnut(designation: str, filters: dict[str, Any]) -> dict[str, Any]:
    filter_count = sum(len(values) for values in filters.values() if isinstance(values, list))
    ccd_value = 860_000 + (filter_count * 5_000)
    non_ccd_value = 140_000 + (filter_count * 2_500)
    total = ccd_value + non_ccd_value
    return _doughnut_chart_payload(
        chart_id=f"{designation}-volume-provider-volume",
        title="Provider Volume",
        explanation="Chart explanation goes here",
        labels=["CCD", "Non CCD"],
        data=[ccd_value, non_ccd_value],
        center_lines=[
            f"{_format_compact(ccd_value)} received",
            "CCD",
            f"out of {_format_compact(total)}",
        ],
        hover_messages=[
            f"CCD providers\nreceived {ccd_value:,} claims",
            f"Non CCD providers\nreceived {non_ccd_value:,} claims",
        ],
    )


def _period_labels(timeline: str) -> list[str]:
    if timeline == "yoy":
        return ["2022", "2023", "2024", "2025 YTD"]
    return ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]


def _series_seed(
    designation: str,
    view_id: str,
    timeline: str,
    filters: dict[str, Any],
    *,
    offset: int = 0,
) -> list[int]:
    filter_count = sum(len(values) for values in filters.values() if isinstance(values, list))
    base = sum(ord(char) for char in f"{designation}:{view_id}:{timeline}") + offset
    periods = len(_period_labels(timeline))
    return [(base + filter_count + (index * 13)) % 85 + 15 for index in range(periods)]


def _bar_chart_payload(
    *,
    chart_id: str,
    labels: list[str],
    data: list[int] | list[list[int]],
) -> dict[str, Any]:
    return {
        "chartId": chart_id,
        "chartType": "bar",
        "labels": labels,
        "data": data,
    }


def _doughnut_chart_payload(
    *,
    chart_id: str,
    title: str,
    explanation: str,
    labels: list[str],
    data: list[int],
    center_lines: list[str],
    hover_messages: list[str],
) -> dict[str, Any]:
    return {
        "chartId": chart_id,
        "chartType": "doughnut",
        "title": title,
        "explanation": explanation,
        "labels": labels,
        "data": data,
        "centerLines": center_lines,
        "hoverMessages": hover_messages,
    }


def _build_mock_charts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Offline-only fallback when Databricks is not configured."""
    designation = str(payload.get("designation") or "ccd").lower()
    view_id = str(payload.get("viewId") or "volume")
    timeline = str(payload.get("timeline") or "ytd").lower()
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else {}

    if view_id == "volume":
        return [
            _provider_group_doughnut(designation, filters),
            _provider_volume_doughnut(designation, filters),
        ]

    labels = _period_labels(timeline)
    primary_values = _series_seed(designation, view_id, timeline, filters)
    comparison_values = _series_seed(designation, view_id, timeline, filters, offset=29)

    return [
        _bar_chart_payload(
            chart_id=f"{designation}-{view_id}-primary",
            labels=labels,
            data=primary_values,
        ),
        _bar_chart_payload(
            chart_id=f"{designation}-{view_id}-comparison",
            labels=labels,
            data=[primary_values, comparison_values],
        ),
    ]


def _compose_chart_payload(
    metadata: ChartMetadata,
    parsed: dict[str, Any],
) -> dict[str, Any]:
    chart_type = metadata.chart_type.lower()
    if chart_type not in _CHART_TYPES:
        raise ValueError(f"Unsupported chart type for {metadata.chart_id}: {metadata.chart_type}")

    if chart_type == "doughnut":
        return _doughnut_chart_payload(
            chart_id=metadata.chart_id,
            title=metadata.name or metadata.chart_id,
            explanation=metadata.description or metadata.tooltip or "Chart explanation goes here",
            labels=parsed["labels"],
            data=parsed["data"],
            center_lines=parsed.get("centerLines", []),
            hover_messages=parsed.get("hoverMessages", []),
        )

    return _bar_chart_payload(
        chart_id=metadata.chart_id,
        labels=parsed["labels"],
        data=parsed["data"],
    )


def _sort_metadata_rows(metadata_rows: list[ChartMetadata]) -> list[ChartMetadata]:
    return sorted(metadata_rows, key=lambda row: (row.sequence, row.chart_id))


def _query_for_context(context: ChartQueryContext, *, use_default: bool = False) -> str:
    if use_default:
        return _default_query(context)
    return build_chart_query(context)


def _fetch_chart_rows(context: ChartQueryContext, *, use_default: bool = False) -> list[dict[str, Any]]:
    query = _query_for_context(context, use_default=use_default)
    return databricks_client.fetch_rows(query)


def _contexts_for_metadata(
    metadata_rows: list[ChartMetadata],
    *,
    dashboard: str,
    designation: str,
    view_id: str,
    timeline: str,
    filters: dict[str, list[str]],
) -> list[ChartQueryContext]:
    return [
        ChartQueryContext(
            dashboard=dashboard,
            designation=designation,
            view=view_id,
            timeline=timeline,
            chart_name=metadata.name or metadata.chart_id,
            chart_type=metadata.chart_type or "bar",
            filters=filters,
            chart_id=metadata.chart_id,
        )
        for metadata in metadata_rows
        if metadata.chart_id
    ]


def _fetch_one_chart_rows(context: ChartQueryContext) -> tuple[str, list[dict[str, Any]]]:
    try:
        return context.chart_id, _fetch_chart_rows(context)
    except Exception:
        return context.chart_id, _fetch_chart_rows(context, use_default=True)


def _fetch_chart_rows_parallel(contexts: list[ChartQueryContext]) -> dict[str, list[dict[str, Any]]]:
    workers = _chart_query_workers(len(contexts))
    if workers == 1:
        chart_id, rows = _fetch_one_chart_rows(contexts[0])
        return {chart_id: rows}

    results = _CHART_EXECUTOR.map(_fetch_one_chart_rows, contexts)
    return dict(results)


def _fetch_chart_rows_batch(contexts: list[ChartQueryContext]) -> dict[str, list[dict[str, Any]]]:
    if not contexts:
        return {}
    if len(contexts) == 1:
        chart_id, rows = _fetch_one_chart_rows(contexts[0])
        return {chart_id: rows}

    try:
        query = build_batch_chart_query(contexts)
        rows = databricks_client.fetch_rows(query)
        rows_by_chart_id = split_batch_rows(rows)
        if rows_by_chart_id:
            return rows_by_chart_id
    except Exception:
        pass

    return _fetch_chart_rows_parallel(contexts)


def _build_chart_from_metadata(
    metadata: ChartMetadata,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    parsed = parse_chart_rows(rows, metadata.chart_type)
    return _compose_chart_payload(metadata, parsed)


def _build_chart_from_metadata_safe(
    metadata: ChartMetadata,
    rows: list[dict[str, Any]] | None,
    *,
    context: ChartQueryContext | None = None,
) -> dict[str, Any] | None:
    try:
        chart_rows = rows
        if not chart_rows and context is not None:
            chart_rows = _fetch_chart_rows(context)
        if not chart_rows:
            return None
        return _build_chart_from_metadata(metadata, chart_rows)
    except Exception:
        if context is None:
            return None
        try:
            fallback_rows = _fetch_chart_rows(context, use_default=True)
            return _build_chart_from_metadata(metadata, fallback_rows)
        except Exception:
            return None


def _resolve_live_metadata(
    *,
    dashboard: str,
    designation: str,
    view_id: str,
    use_live_data: bool,
) -> list[ChartMetadata]:
    rows = resolve_chart_metadata(
        dashboard=dashboard,
        designation=designation,
        view=view_id,
        use_live_data=use_live_data,
    )
    return _sort_metadata_rows(rows)


def _fetch_metadata_and_chart_rows_parallel(
    *,
    dashboard: str,
    designation: str,
    view_id: str,
    timeline: str,
    filters: dict[str, list[str]],
    use_live_data: bool,
) -> tuple[list[ChartMetadata], dict[str, list[dict[str, Any]]]]:
    """Fetch live metadata and chart data concurrently.

    Chart IDs are deterministic per dashboard/designation/view, so the batch
    chart-data query can start from the local catalog without waiting on
    ``jw_chart_metadata``. Live metadata still drives titles and order.
    """
    catalog_rows = catalog_metadata_rows(
        dashboard=dashboard,
        designation=designation,
        view=view_id,
    )
    data_contexts = _contexts_for_metadata(
        catalog_rows,
        dashboard=dashboard,
        designation=designation,
        view_id=view_id,
        timeline=timeline,
        filters=filters,
    )

    metadata_future = _CHART_EXECUTOR.submit(
        _resolve_live_metadata,
        dashboard=dashboard,
        designation=designation,
        view_id=view_id,
        use_live_data=use_live_data,
    )
    chart_rows_future = _CHART_EXECUTOR.submit(_fetch_chart_rows_batch, data_contexts)
    wait([metadata_future, chart_rows_future])

    metadata_rows = metadata_future.result()
    rows_by_chart_id = chart_rows_future.result()
    if not metadata_rows:
        metadata_rows = catalog_rows
    return metadata_rows, rows_by_chart_id


def _build_charts_for_metadata(
    metadata_rows: list[ChartMetadata],
    rows_by_chart_id: dict[str, list[dict[str, Any]]],
    *,
    dashboard: str,
    designation: str,
    view_id: str,
    timeline: str,
    filters: dict[str, list[str]],
) -> list[dict[str, Any]]:
    active_rows = [row for row in metadata_rows if row.chart_id]
    if not active_rows:
        return []

    contexts = _contexts_for_metadata(
        active_rows,
        dashboard=dashboard,
        designation=designation,
        view_id=view_id,
        timeline=timeline,
        filters=filters,
    )

    charts: list[dict[str, Any]] = []
    for metadata, context in zip(active_rows, contexts, strict=True):
        chart = _build_chart_from_metadata_safe(
            metadata,
            rows_by_chart_id.get(metadata.chart_id),
            context=context,
        )
        if chart is not None:
            charts.append(chart)
    return charts


def build_charts(payload: dict[str, Any], *, use_live_data: bool = True) -> list[dict[str, Any]]:
    dashboard = str(payload.get("dashboard") or DEFAULT_DASHBOARD).strip() or DEFAULT_DASHBOARD
    designation = str(payload.get("designation") or "ccd").lower()
    view_id = str(payload.get("viewId") or "volume")
    timeline = str(payload.get("timeline") or "ytd").lower()
    filters = normalize_filters(payload.get("filters"))

    if not databricks_client.is_configured():
        return _build_mock_charts(payload)

    databricks_client.warm_connection()

    metadata_rows, rows_by_chart_id = _fetch_metadata_and_chart_rows_parallel(
        dashboard=dashboard,
        designation=designation,
        view_id=view_id,
        timeline=timeline,
        filters=filters,
        use_live_data=use_live_data,
    )

    return _build_charts_for_metadata(
        metadata_rows,
        rows_by_chart_id,
        dashboard=dashboard,
        designation=designation,
        view_id=view_id,
        timeline=timeline,
        filters=filters,
    )
