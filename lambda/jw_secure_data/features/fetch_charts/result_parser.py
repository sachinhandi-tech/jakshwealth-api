"""Parse Databricks chart query rows into API chart payload fields."""

from __future__ import annotations

from typing import Any


def _row_value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
        lowered = key.lower()
        if lowered in row:
            return row[lowered]
        upper = key.upper()
        if upper in row:
            return row[upper]
    return None


def _as_int(value: Any) -> int:
    if value is None:
        return 0
    return int(value)


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def parse_chart_rows(rows: list[dict[str, Any]], chart_type: str) -> dict[str, Any]:
    """Extract labels, data, centerLines, and hoverMessages from query rows."""
    slices = [
        row for row in rows if _as_str(_row_value(row, "row_kind")).lower() == "slice"
    ]
    centers = [
        row for row in rows if _as_str(_row_value(row, "row_kind")).lower() == "center"
    ]

    slices.sort(
        key=lambda row: (
            _as_int(_row_value(row, "series_index")),
            _as_int(_row_value(row, "sort_order")),
        )
    )
    centers.sort(key=lambda row: _as_int(_row_value(row, "sort_order")))

    chart_type = chart_type.lower()
    if chart_type == "doughnut":
        labels = [_as_str(_row_value(row, "label")) for row in slices]
        data = [_as_int(_row_value(row, "data_value")) for row in slices]
        center_lines = [
            _as_str(_row_value(row, "center_line"))
            for row in centers
            if _as_str(_row_value(row, "center_line"))
        ]
        hover_messages = [
            _as_str(_row_value(row, "hover_message"))
            for row in slices
            if _as_str(_row_value(row, "hover_message"))
        ]
        return {
            "labels": labels,
            "data": data,
            "centerLines": center_lines,
            "hoverMessages": hover_messages,
        }

    if chart_type == "bar":
        series_indices = sorted(
            {_as_int(_row_value(row, "series_index")) for row in slices}
        )
        primary_slices = [
            row
            for row in slices
            if _as_int(_row_value(row, "series_index")) == series_indices[0]
        ]
        labels = [_as_str(_row_value(row, "label")) for row in primary_slices]
        if len(series_indices) == 1:
            data = [_as_int(_row_value(row, "data_value")) for row in primary_slices]
        else:
            data = [
                [
                    _as_int(_row_value(row, "data_value"))
                    for row in slices
                    if _as_int(_row_value(row, "series_index")) == series_index
                ]
                for series_index in series_indices
            ]
        return {"labels": labels, "data": data}

    raise ValueError(f"Unsupported chart type: {chart_type!r}")
