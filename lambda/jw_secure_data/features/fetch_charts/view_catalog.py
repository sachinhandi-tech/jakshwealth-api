"""Static chart layout catalog synced from ``jw_chart_metadata``.

Chart IDs for a view are deterministic from dashboard + designation + view, so
chart-data SQL can start without waiting on the metadata warehouse query.
Live metadata remains the source of truth for titles, ordering, and new charts.
"""

from __future__ import annotations

from features.fetch_charts.chart_catalog import CHART_CATALOG
from features.fetch_charts.models import DEFAULT_DASHBOARD, ChartMetadata


def catalog_metadata_rows(
    *,
    dashboard: str,
    designation: str,
    view: str,
) -> list[ChartMetadata]:
    """Return catalog metadata for a view so chart-data queries can start immediately."""
    dashboard_type = dashboard or DEFAULT_DASHBOARD
    designation = designation.lower()
    rows: list[ChartMetadata] = []
    sequence = 0
    for chart_id, chart_designation, view_name, chart_type, name in CHART_CATALOG:
        if chart_designation != designation or view_name != view:
            continue
        rows.append(
            ChartMetadata(
                chart_id=chart_id,
                name=name,
                description="Chart explanation goes here",
                tooltip="",
                sequence=sequence,
                dashboard_type=dashboard_type,
                designation=chart_designation,
                view_name=view_name,
                chart_type=chart_type,
            )
        )
        sequence += 1
    return rows
