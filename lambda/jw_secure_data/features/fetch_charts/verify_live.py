#!/usr/bin/env python3
"""Verify fetch-charts for all proof-points combinations against live Databricks."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
LAMBDA_DIR = ROOT / "lambda" / "jw_secure_data"
sys.path.insert(0, str(LAMBDA_DIR))

os.environ.setdefault("ENVIRONMENT", "local")
os.environ.setdefault("LOCAL_CONFIG_FILE", str(ROOT / "config.local.json"))

import config  # noqa: E402

config.load_config()

import databricks_client  # noqa: E402
from features.fetch_charts.metadata import METADATA_QUERY, fetch_chart_metadata  # noqa: E402
from features.fetch_charts.service import build_charts  # noqa: E402

DESIGNATIONS = ("ccd", "tier-1")
VIEWS = (
    "volume",
    "spend",
    "utilization",
    "savings",
    "quality",
    "turnover-disruption",
)
TIMELINES = ("ytd", "yoy")

EMPTY_FILTERS = {
    "crrMarket": [],
    "providerNetwork": [],
    "specialtyCategory": [],
    "specialtyType": [],
    "episodeCategory": [],
    "memberProduct": [],
}


def _validate_chart(chart: dict) -> list[str]:
    errors: list[str] = []
    chart_id = chart.get("chartId", "<missing>")
    chart_type = chart.get("chartType")
    labels = chart.get("labels")
    data = chart.get("data")

    if not chart_id:
        errors.append("missing chartId")
    if chart_type not in {"bar", "doughnut"}:
        errors.append(f"{chart_id}: invalid chartType {chart_type!r}")

    if not isinstance(labels, list) or not labels:
        errors.append(f"{chart_id}: labels must be a non-empty list")

    if chart_type == "bar":
        if isinstance(data, list) and data and isinstance(data[0], list):
            for series in data:
                if len(series) != len(labels):
                    errors.append(f"{chart_id}: series length mismatch")
                if any(value < 0 for value in series):
                    errors.append(f"{chart_id}: negative bar value")
        elif isinstance(data, list):
            if len(data) != len(labels):
                errors.append(f"{chart_id}: data length mismatch")
            if any(value < 0 for value in data):
                errors.append(f"{chart_id}: negative bar value")
        else:
            errors.append(f"{chart_id}: bar data must be a list")
    elif chart_type == "doughnut":
        if not isinstance(data, list) or len(data) != len(labels):
            errors.append(f"{chart_id}: doughnut data/labels mismatch")
        if not chart.get("centerLines"):
            errors.append(f"{chart_id}: missing centerLines")
        if not chart.get("hoverMessages"):
            errors.append(f"{chart_id}: missing hoverMessages")
        if any(value < 0 for value in data or []):
            errors.append(f"{chart_id}: negative doughnut value")

    return errors


def main() -> int:
    if not databricks_client.is_configured():
        print("Databricks is not configured; cannot run live verification.")
        return 1

    print("Databricks configured:", databricks_client.is_configured())
    print("Metadata query preview:\n", METADATA_QUERY.strip())

    failures: list[str] = []
    for designation in DESIGNATIONS:
        for view in VIEWS:
            try:
                metadata = fetch_chart_metadata(
                    dashboard="proof-points",
                    designation=designation,
                    view=view,
                )
                print(f"metadata {designation}/{view}: {len(metadata)} charts")
            except Exception as exc:  # pragma: no cover - live verification
                failures.append(f"metadata {designation}/{view}: {exc}")
                metadata = []

            for timeline in TIMELINES:
                payload = {
                    "dashboard": "proof-points",
                    "designation": designation,
                    "viewId": view,
                    "timeline": timeline,
                    "filters": EMPTY_FILTERS,
                }
                try:
                    charts = build_charts(payload, use_live_data=True)
                except Exception as exc:  # pragma: no cover - live verification
                    failures.append(f"build {designation}/{view}/{timeline}: {exc}")
                    continue

                expected_count = len(metadata)
                if len(charts) != expected_count:
                    failures.append(
                        f"build {designation}/{view}/{timeline}: expected {expected_count} charts from metadata, got {len(charts)}"
                    )
                    continue

                expected_ids = [row.chart_id for row in metadata]
                actual_ids = [chart["chartId"] for chart in charts]
                if actual_ids != expected_ids:
                    failures.append(
                        f"build {designation}/{view}/{timeline}: chart order/id mismatch expected {expected_ids}, got {actual_ids}"
                    )

                for chart in charts:
                    failures.extend(_validate_chart(chart))

                print(
                    f"ok {designation}/{view}/{timeline} -> "
                    + ", ".join(chart["chartId"] for chart in charts)
                )

    if failures:
        print("\nFAILURES:")
        for failure in failures:
            print("-", failure)
        return 1

    print("\nAll proof-points fetch-charts combinations verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
