"""Chart metadata access from Databricks."""

from __future__ import annotations

from typing import Any

import databricks_client
from features.fetch_charts.models import DEFAULT_DASHBOARD, ChartMetadata

METADATA_TABLE = "usm_dev.jw_reporting.jw_chart_metadata"

METADATA_QUERY = f"""
SELECT
    chart_id,
    name,
    description,
    tooltip,
    sequence,
    dashboard_type,
    designation,
    view_name,
    chart_type,
    change_version
FROM {METADATA_TABLE}
WHERE dashboard_type = ?
  AND designation = ?
  AND view_name = ?
ORDER BY sequence, chart_id
"""


def fetch_chart_metadata(
    *,
    dashboard: str,
    designation: str,
    view: str,
) -> list[ChartMetadata]:
    rows = databricks_client.fetch_rows_with_params(
        METADATA_QUERY,
        [dashboard or DEFAULT_DASHBOARD, designation, view],
    )
    return [ChartMetadata.from_row(row) for row in rows if row]


def fallback_chart_metadata(
    *,
    designation: str,
    view: str,
) -> list[ChartMetadata]:
    """Local fallback when metadata warehouse access is unavailable."""
    if view == "volume":
        chart_defs = [
            ("provider-groups", "Provider Group Volume", "doughnut"),
            ("provider-volume", "Provider Volume", "doughnut"),
        ]
    else:
        chart_defs = [
            ("primary", f"{view.replace('-', ' ').title()} primary", "bar"),
            ("comparison", f"{view.replace('-', ' ').title()} comparison", "bar"),
        ]

    return [
        ChartMetadata(
            chart_id=f"{designation}-{view}-{suffix}",
            name=title if view != "volume" else title,
            description="Chart explanation goes here",
            tooltip="",
            sequence=index,
            dashboard_type=DEFAULT_DASHBOARD,
            designation=designation,
            view_name=view,
            chart_type=chart_type,
        )
        for index, (suffix, title, chart_type) in enumerate(chart_defs)
    ]


def resolve_chart_metadata(
    *,
    dashboard: str,
    designation: str,
    view: str,
    use_live_data: bool,
) -> list[ChartMetadata]:
    if use_live_data and databricks_client.is_configured():
        try:
            return fetch_chart_metadata(
                dashboard=dashboard,
                designation=designation,
                view=view,
            )
        except Exception:
            pass
    return fallback_chart_metadata(designation=designation, view=view)
