"""Shared models for fetch-charts metadata and query composition."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_DASHBOARD = "proof-points"

FILTER_KEYS = (
    "crrMarket",
    "providerNetwork",
    "specialtyCategory",
    "specialtyType",
    "episodeCategory",
    "memberProduct",
)

FILTER_COLUMN_MAP = {
    "crrMarket": "crr_market",
    "providerNetwork": "provider_network",
    "specialtyCategory": "specialty_category",
    "specialtyType": "specialty_type",
    "episodeCategory": "episode_category",
    "memberProduct": "member_product",
}


@dataclass(frozen=True)
class ChartQueryContext:
    dashboard: str
    designation: str
    view: str
    timeline: str
    chart_name: str
    chart_type: str = "bar"
    filters: dict[str, list[str]] = field(default_factory=dict)
    chart_id: str = ""


@dataclass(frozen=True)
class ChartMetadata:
    chart_id: str
    name: str
    description: str
    tooltip: str
    sequence: int
    dashboard_type: str
    designation: str
    view_name: str
    chart_type: str
    change_version: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ChartMetadata:
        return cls(
            chart_id=str(row.get("chart_id") or row.get("CHART_ID") or "").strip(),
            name=str(row.get("name") or row.get("NAME") or "").strip(),
            description=str(row.get("description") or row.get("DESCRIPTION") or "").strip(),
            tooltip=str(row.get("tooltip") or row.get("TOOLTIP") or "").strip(),
            sequence=int(row.get("sequence") or row.get("SEQUENCE") or 0),
            dashboard_type=str(
                row.get("dashboard_type") or row.get("DASHBOARD_TYPE") or ""
            ).strip(),
            designation=str(row.get("designation") or row.get("DESIGNATION") or "").strip(),
            view_name=str(row.get("view_name") or row.get("VIEW_NAME") or "").strip(),
            chart_type=str(row.get("chart_type") or row.get("CHART_TYPE") or "").strip(),
            change_version=(
                str(row.get("change_version") or row.get("CHANGE_VERSION") or "").strip()
                or None
            ),
        )


def normalize_filters(raw: dict[str, Any] | None) -> dict[str, list[str]]:
    filters = raw if isinstance(raw, dict) else {}
    normalized: dict[str, list[str]] = {}
    for key in FILTER_KEYS:
        values = filters.get(key, [])
        if not isinstance(values, list):
            continue
        cleaned = [str(value).strip() for value in values if str(value).strip()]
        normalized[key] = cleaned
    return normalized


def filter_offset(filters: dict[str, list[str]]) -> int:
    return sum(len(values) for values in filters.values())
