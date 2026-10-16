from unittest.mock import patch

import databricks_client
from features.fetch_charts.metadata import fallback_chart_metadata, resolve_chart_metadata
from features.fetch_charts.models import ChartMetadata, ChartQueryContext, normalize_filters
from features.fetch_charts.query_library.batch import build_batch_chart_query, split_batch_rows
from features.fetch_charts.query_library.builder import build_chart_query
from features.fetch_charts.query_library.filters import build_filter_clause
from features.fetch_charts.query_library.registry import resolve_chart_id
from features.fetch_charts.result_parser import parse_chart_rows
from features.fetch_charts.service import build_charts
from features.fetch_charts.view_catalog import catalog_metadata_rows

DOUGHNUT_KEYS = {
    "chartId",
    "chartType",
    "title",
    "explanation",
    "labels",
    "data",
    "centerLines",
    "hoverMessages",
}


def _doughnut_batch_rows(*chart_ids: str) -> list[dict]:
    rows: list[dict] = []
    for chart_id in chart_ids:
        rows.extend(
            [
                {
                    "chart_id": chart_id,
                    "row_kind": "slice",
                    "sort_order": 0,
                    "label": "CCD",
                    "data_value": 160000,
                    "series_index": 0,
                    "hover_message": f"CCD {chart_id}\nreceived 160,000 claims",
                },
                {
                    "chart_id": chart_id,
                    "row_kind": "slice",
                    "sort_order": 1,
                    "label": "Non CCD",
                    "data_value": 40000,
                    "series_index": 0,
                    "hover_message": f"Non CCD {chart_id}\nreceived 40,000 claims",
                },
                {"chart_id": chart_id, "row_kind": "center", "sort_order": 0, "center_line": "160K"},
                {"chart_id": chart_id, "row_kind": "center", "sort_order": 1, "center_line": "received CCD"},
                {"chart_id": chart_id, "row_kind": "center", "sort_order": 2, "center_line": "out of 200K"},
            ]
        )
    return rows


def test_normalize_filters_keeps_supported_keys_only():
    filters = normalize_filters(
        {
            "crrMarket": ["east"],
            "providerNetwork": ["in-network", "out-of-network"],
            "unexpected": ["x"],
        }
    )
    assert filters == {
        "crrMarket": ["east"],
        "providerNetwork": ["in-network", "out-of-network"],
        "specialtyCategory": [],
        "specialtyType": [],
        "episodeCategory": [],
        "memberProduct": [],
    }


def test_build_filter_clause_includes_selected_values():
    clause = build_filter_clause({"crrMarket": ["East", "West"]})
    assert clause == " AND crr_market IN ('East', 'West')"


def test_build_chart_query_uses_default_for_unknown_chart_name():
    query = build_chart_query(
        ChartQueryContext(
            dashboard="proof-points",
            designation="ccd",
            view="spend",
            timeline="ytd",
            chart_name="Unknown Chart",
            chart_type="doughnut",
            filters={},
        )
    )
    assert "FROM VALUES" in query


def test_build_chart_query_returns_sql_for_registered_chart():
    query = build_chart_query(
        ChartQueryContext(
            dashboard="proof-points",
            designation="ccd",
            view="volume",
            timeline="ytd",
            chart_name="Provider Group Volume",
            chart_id="1",
            chart_type="doughnut",
            filters={},
        )
    )
    assert "FROM VALUES" in query


def test_resolve_chart_id_prefers_metadata_id_over_name():
    chart_id = resolve_chart_id(
        ChartQueryContext(
            dashboard="proof-points",
            designation="tier-1",
            view="quality",
            timeline="yoy",
            chart_name="Renamed In Metadata",
            chart_id="117",
            chart_type="doughnut",
            filters={},
        )
    )
    assert chart_id == "117"


def test_parse_doughnut_rows_extracts_labels_data_center_and_hover():
    rows = [
        {
            "row_kind": "slice",
            "sort_order": 0,
            "label": "CCD",
            "data_value": 160000,
            "series_index": 0,
            "hover_message": "CCD provider groups\nreceived 160,000 claims",
        },
        {
            "row_kind": "slice",
            "sort_order": 1,
            "label": "Non CCD",
            "data_value": 40000,
            "series_index": 0,
            "hover_message": "Non CCD provider groups\nreceived 40,000 claims",
        },
        {
            "row_kind": "center",
            "sort_order": 0,
            "center_line": "160K",
        },
        {
            "row_kind": "center",
            "sort_order": 1,
            "center_line": "received CCD",
        },
        {
            "row_kind": "center",
            "sort_order": 2,
            "center_line": "out of 200K",
        },
    ]
    parsed = parse_chart_rows(rows, "doughnut")
    assert parsed["labels"] == ["CCD", "Non CCD"]
    assert parsed["data"] == [160000, 40000]
    assert parsed["centerLines"] == ["160K", "received CCD", "out of 200K"]
    assert len(parsed["hoverMessages"]) == 2


def test_parse_bar_comparison_rows_builds_matrix_data():
    rows = [
        {"row_kind": "slice", "sort_order": 0, "label": "Jan", "data_value": 20, "series_index": 0},
        {"row_kind": "slice", "sort_order": 0, "label": "Jan", "data_value": 30, "series_index": 1},
        {"row_kind": "slice", "sort_order": 1, "label": "Feb", "data_value": 25, "series_index": 0},
        {"row_kind": "slice", "sort_order": 1, "label": "Feb", "data_value": 35, "series_index": 1},
    ]
    parsed = parse_chart_rows(rows, "bar")
    assert parsed["labels"] == ["Jan", "Feb"]
    assert parsed["data"] == [[20, 25], [30, 35]]


def test_fallback_chart_metadata_matches_volume_and_bar_views():
    volume = fallback_chart_metadata(designation="ccd", view="volume")
    spend = fallback_chart_metadata(designation="ccd", view="spend")
    assert [chart.chart_id for chart in volume] == [
        "ccd-volume-provider-groups",
        "ccd-volume-provider-volume",
    ]
    assert [chart.chart_id for chart in spend] == [
        "ccd-spend-primary",
        "ccd-spend-comparison",
    ]


@patch.object(databricks_client, "is_configured", return_value=False)
def test_build_charts_returns_chart_id_type_labels_and_data(_mock_configured):
    charts = build_charts(
        {
            "dashboard": "proof-points",
            "designation": "ccd",
            "viewId": "spend",
            "timeline": "yoy",
            "filters": {"crrMarket": ["east"]},
        }
    )
    assert len(charts) == 2
    primary = charts[0]
    comparison = charts[1]
    assert set(primary.keys()) == {"chartId", "chartType", "labels", "data"}
    assert primary["chartId"] == "ccd-spend-primary"
    assert primary["chartType"] == "bar"


@patch.object(databricks_client, "is_configured", return_value=False)
def test_build_charts_includes_two_doughnuts_for_volume(_mock_configured):
    charts = build_charts(
        {
            "dashboard": "proof-points",
            "designation": "ccd",
            "viewId": "volume",
            "timeline": "ytd",
            "filters": {},
        }
    )
    assert len(charts) == 2
    provider_groups = charts[0]
    provider_volume = charts[1]
    assert set(provider_groups.keys()) == DOUGHNUT_KEYS
    assert provider_groups["chartId"] == "ccd-volume-provider-groups"
    assert provider_groups["chartType"] == "doughnut"
    assert provider_groups["title"] == "Provider Group Volume"
    assert provider_groups["explanation"] == "Chart explanation goes here"
    assert provider_groups["labels"] == ["CCD", "Non CCD"]
    assert provider_groups["data"] == [160_000, 40_000]
    assert provider_groups["centerLines"] == ["160K", "received CCD", "out of 200K"]
    assert provider_groups["hoverMessages"] == [
        "CCD provider groups\nreceived 160,000 claims",
        "Non CCD provider groups\nreceived 40,000 claims",
    ]
    assert set(provider_volume.keys()) == DOUGHNUT_KEYS
    assert provider_volume["chartId"] == "ccd-volume-provider-volume"
    assert provider_volume["chartType"] == "doughnut"
    assert provider_volume["title"] == "Provider Volume"
    assert provider_volume["explanation"] == "Chart explanation goes here"
    assert provider_volume["labels"] == ["CCD", "Non CCD"]
    assert provider_volume["data"] == [860_000, 140_000]
    assert provider_volume["centerLines"] == ["860K received", "CCD", "out of 1M"]
    assert provider_volume["hoverMessages"] == [
        "CCD providers\nreceived 860,000 claims",
        "Non CCD providers\nreceived 140,000 claims",
    ]


@patch.object(databricks_client, "is_configured", return_value=False)
def test_build_charts_varies_by_view(_mock_configured):
    volume = build_charts(
        {
            "dashboard": "proof-points",
            "designation": "ccd",
            "viewId": "volume",
            "timeline": "ytd",
            "filters": {},
        }
    )
    quality = build_charts(
        {
            "dashboard": "proof-points",
            "designation": "ccd",
            "viewId": "quality",
            "timeline": "ytd",
            "filters": {},
        }
    )
    assert len(volume) == 2
    assert volume[0]["chartType"] == "doughnut"
    assert len(quality) == 2
    assert quality[0]["chartType"] == "bar"


def test_catalog_metadata_rows_for_spend_view():
    rows = catalog_metadata_rows(
        dashboard="proof-points",
        designation="ccd",
        view="spend",
    )
    assert [row.chart_id for row in rows] == ["3", "4", "5", "6", "7", "8"]
    assert all(row.chart_type == "doughnut" for row in rows)


def test_build_batch_chart_query_unions_chart_sql():
    contexts = [
        ChartQueryContext(
            dashboard="proof-points",
            designation="ccd",
            view="spend",
            timeline="ytd",
            chart_name="Gross Episode Spend",
            chart_id="3",
            chart_type="doughnut",
            filters={},
        ),
        ChartQueryContext(
            dashboard="proof-points",
            designation="ccd",
            view="spend",
            timeline="ytd",
            chart_name="Gross Episode Counts",
            chart_id="4",
            chart_type="doughnut",
            filters={},
        ),
    ]
    query = build_batch_chart_query(contexts)
    assert "UNION ALL" in query
    assert "'3' AS chart_id" in query
    assert "'4' AS chart_id" in query


def test_split_batch_rows_groups_by_chart_id():
    rows = _doughnut_batch_rows("3", "4")
    grouped = split_batch_rows(rows)
    assert set(grouped) == {"3", "4"}
    assert len(grouped["3"]) == 5
    assert "chart_id" not in grouped["3"][0]


@patch.object(databricks_client, "fetch_rows")
@patch.object(databricks_client, "is_configured", return_value=True)
def test_build_charts_renders_all_metadata_charts(_mock_configured, mock_fetch_rows):
    mock_fetch_rows.return_value = _doughnut_batch_rows("3", "4")

    metadata_rows = [
        ChartMetadata(
            chart_id="3",
            name="Extra",
            description="Extra spend chart",
            tooltip="",
            sequence=0,
            dashboard_type="proof-points",
            designation="ccd",
            view_name="spend",
            chart_type="doughnut",
        ),
        ChartMetadata(
            chart_id="4",
            name="Spend Primary",
            description="",
            tooltip="",
            sequence=1,
            dashboard_type="proof-points",
            designation="ccd",
            view_name="spend",
            chart_type="doughnut",
        ),
    ]

    with patch(
        "features.fetch_charts.service.resolve_chart_metadata",
        return_value=metadata_rows,
    ):
        charts = build_charts(
            {
                "dashboard": "proof-points",
                "designation": "ccd",
                "viewId": "spend",
                "timeline": "ytd",
                "filters": {},
            }
        )

    assert len(charts) == 2
    assert [chart["chartId"] for chart in charts] == ["3", "4"]
    assert mock_fetch_rows.call_count == 1


@patch.object(databricks_client, "fetch_rows")
@patch.object(databricks_client, "is_configured", return_value=True)
def test_build_charts_fetches_charts_in_single_batch(_mock_configured, mock_fetch_rows):
    import time

    def _slow_fetch(_query, params=None):
        time.sleep(0.05)
        return _doughnut_batch_rows("3", "4", "5", "6")

    mock_fetch_rows.side_effect = _slow_fetch

    metadata_rows = [
        ChartMetadata(
            chart_id=str(chart_id),
            name=f"Chart {chart_id}",
            description="",
            tooltip="",
            sequence=index,
            dashboard_type="proof-points",
            designation="ccd",
            view_name="spend",
            chart_type="doughnut",
        )
        for index, chart_id in enumerate(["3", "4", "5", "6"], start=1)
    ]

    started = time.monotonic()
    with patch(
        "features.fetch_charts.service.resolve_chart_metadata",
        return_value=metadata_rows,
    ):
        charts = build_charts(
            {
                "dashboard": "proof-points",
                "designation": "ccd",
                "viewId": "spend",
                "timeline": "ytd",
                "filters": {},
            }
        )
    elapsed = time.monotonic() - started

    assert [chart["chartId"] for chart in charts] == ["3", "4", "5", "6"]
    assert mock_fetch_rows.call_count == 1
    assert elapsed < 0.15


@patch.object(databricks_client, "fetch_rows")
@patch.object(databricks_client, "is_configured", return_value=True)
def test_build_charts_fetches_metadata_and_data_in_parallel(_mock_configured, mock_fetch_rows):
    import time

    def _slow_fetch(query, params=None):
        time.sleep(0.05)
        if params:
            return []
        return _doughnut_batch_rows("3", "4", "5", "6")

    def _slow_metadata(*_args, **_kwargs):
        time.sleep(0.05)
        return [
            ChartMetadata(
                chart_id=str(chart_id),
                name=f"Chart {chart_id}",
                description="",
                tooltip="",
                sequence=index,
                dashboard_type="proof-points",
                designation="ccd",
                view_name="spend",
                chart_type="doughnut",
            )
            for index, chart_id in enumerate(["3", "4", "5", "6"], start=1)
        ]

    mock_fetch_rows.side_effect = _slow_fetch

    started = time.monotonic()
    with patch(
        "features.fetch_charts.service.resolve_chart_metadata",
        side_effect=_slow_metadata,
    ):
        charts = build_charts(
            {
                "dashboard": "proof-points",
                "designation": "ccd",
                "viewId": "spend",
                "timeline": "ytd",
                "filters": {},
            }
        )
    elapsed = time.monotonic() - started

    assert len(charts) == 4
    assert mock_fetch_rows.call_count == 1
    assert elapsed < 0.12


@patch.object(databricks_client, "fetch_rows")
@patch.object(databricks_client, "is_configured", return_value=True)
def test_build_charts_uses_metadata_and_query_results(_mock_configured, mock_fetch_rows):
    fallback_rows = resolve_chart_metadata(
        dashboard="proof-points",
        designation="ccd",
        view="volume",
        use_live_data=False,
    )
    chart_ids = [row.chart_id for row in fallback_rows]
    mock_fetch_rows.return_value = _doughnut_batch_rows(*chart_ids)

    with patch(
        "features.fetch_charts.service.resolve_chart_metadata",
        return_value=resolve_chart_metadata(
            dashboard="proof-points",
            designation="ccd",
            view="volume",
            use_live_data=False,
        ),
    ):
        charts = build_charts(
            {
                "dashboard": "proof-points",
                "designation": "ccd",
                "viewId": "volume",
                "timeline": "ytd",
                "filters": {},
            }
        )

    assert len(charts) == 2
    assert charts[0]["data"] == [160_000, 40_000]
    assert charts[1]["data"] == [160_000, 40_000]
    assert mock_fetch_rows.call_count == 1
