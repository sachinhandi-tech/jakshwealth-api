"""Chart SQL query implementations.

Replace SQL inside ``build_query_chart_<id>_<timeline>`` when warehouse logic is ready.
Lookup uses stable ``chart_id`` + timeline via ``registry.py`` (not long function names).

Regenerate scaffold sections after metadata changes::

    python3 generate_queries_file.py
"""

from __future__ import annotations

from collections.abc import Callable

from features.fetch_charts.models import ChartQueryContext, filter_offset
from features.fetch_charts.query_library.filters import build_filter_clause_for_context
from features.fetch_charts.query_library.registry import BuilderKey, resolve_query_builder

QueryBuilder = Callable[[ChartQueryContext], str]


def _period_labels(timeline: str) -> list[str]:
    if timeline == "yoy":
        return ["2022", "2023", "2024", "2025 YTD"]
    return ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]


def _seed_base(context: ChartQueryContext, *, offset: int = 0) -> int:
    return (
        sum(
            ord(char)
            for char in (
                f"{context.dashboard}:{context.designation}:{context.view}:"
                f"{context.timeline}:{context.chart_id or context.chart_name}"
            )
        )
        + offset
    )


def _compact(value: int) -> str:
    absolute = abs(int(value))
    if absolute >= 1_000_000:
        millions = absolute / 1_000_000
        return f"{int(millions)}M" if millions.is_integer() else f"{millions:.1f}M"
    if absolute >= 1_000:
        thousands = absolute / 1_000
        return f"{int(thousands)}K" if thousands.is_integer() else f"{thousands:.1f}K"
    return f"{absolute:,}"


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _is_comparison_bar(context: ChartQueryContext) -> bool:
    return (
        context.chart_type.lower() == "bar"
        and context.chart_name.lower().endswith("comparison")
    )


def _doughnut_query(context: ChartQueryContext) -> str:
    filter_count = filter_offset(context.filters)
    filter_clause = build_filter_clause_for_context(context)
    seed = _seed_base(context)
    primary = 120_000 + (filter_count * 900) + (seed % 40_000)
    secondary = 35_000 + (filter_count * 450) + (seed % 15_000)
    total = primary + secondary
    center_line_1 = _compact(primary)
    center_line_2 = "received CCD"
    center_line_3 = "out of " + _compact(total)
    label = context.chart_name or context.chart_id
    return f"""
SELECT
    sort_order,
    row_kind,
    label,
    data_value,
    series_index,
    center_line,
    hover_message
FROM VALUES
    (0, 'slice', 'CCD', {primary}, 0, CAST(NULL AS STRING), CONCAT('CCD ', {_sql_literal(label)}, CHAR(10), 'received ', FORMAT_NUMBER({primary}, 0))),
    (1, 'slice', 'Non CCD', {secondary}, 0, CAST(NULL AS STRING), CONCAT('Non CCD ', {_sql_literal(label)}, CHAR(10), 'received ', FORMAT_NUMBER({secondary}, 0))),
    (0, 'center', CAST(NULL AS STRING), CAST(NULL AS DOUBLE), 0, {_sql_literal(center_line_1)}, CAST(NULL AS STRING)),
    (1, 'center', CAST(NULL AS STRING), CAST(NULL AS DOUBLE), 0, {_sql_literal(center_line_2)}, CAST(NULL AS STRING)),
    (2, 'center', CAST(NULL AS STRING), CAST(NULL AS DOUBLE), 0, {_sql_literal(center_line_3)}, CAST(NULL AS STRING))
AS chart_data(sort_order, row_kind, label, data_value, series_index, center_line, hover_message)
WHERE 1 = 1{filter_clause}
ORDER BY row_kind DESC, sort_order, series_index
"""


def _primary_bar_query(context: ChartQueryContext) -> str:
    filter_count = filter_offset(context.filters)
    filter_clause = build_filter_clause_for_context(context)
    base = _seed_base(context)
    labels = _period_labels(context.timeline)
    rows = []
    for index, label in enumerate(labels):
        value = (base + filter_count + (index * 13)) % 85 + 15
        rows.append(
            f"({index}, 'slice', '{label}', {value}, 0, CAST(NULL AS STRING), CAST(NULL AS STRING))"
        )
    value_rows = ",\n    ".join(rows)
    return f"""
SELECT
    sort_order,
    row_kind,
    label,
    data_value,
    series_index,
    center_line,
    hover_message
FROM VALUES
    {value_rows}
AS chart_data(sort_order, row_kind, label, data_value, series_index, center_line, hover_message)
WHERE 1 = 1{filter_clause}
ORDER BY sort_order, series_index
"""


def _comparison_bar_query(context: ChartQueryContext) -> str:
    filter_count = filter_offset(context.filters)
    filter_clause = build_filter_clause_for_context(context)
    primary_base = _seed_base(context)
    comparison_base = _seed_base(context, offset=29)
    labels = _period_labels(context.timeline)
    rows = []
    for index, label in enumerate(labels):
        primary = (primary_base + filter_count + (index * 13)) % 85 + 15
        comparison = (comparison_base + filter_count + (index * 13)) % 85 + 15
        rows.append(
            f"({index}, 'slice', '{label}', {primary}, 0, CAST(NULL AS STRING), CAST(NULL AS STRING))"
        )
        rows.append(
            f"({index}, 'slice', '{label}', {comparison}, 1, CAST(NULL AS STRING), CAST(NULL AS STRING))"
        )
    value_rows = ",\n    ".join(rows)
    return f"""
SELECT
    sort_order,
    row_kind,
    label,
    data_value,
    series_index,
    center_line,
    hover_message
FROM VALUES
    {value_rows}
AS chart_data(sort_order, row_kind, label, data_value, series_index, center_line, hover_message)
WHERE 1 = 1{filter_clause}
ORDER BY sort_order, series_index
"""


def _default_query(context: ChartQueryContext) -> str:
    chart_type = context.chart_type.lower()
    if chart_type == "doughnut":
        return _doughnut_query(context)
    if _is_comparison_bar(context):
        return _comparison_bar_query(context)
    if chart_type == "bar":
        return _primary_bar_query(context)
    raise ValueError(f"Unsupported chart type: {context.chart_type!r}")



# Chart 1 — Provider Group Volume (ccd / volume / YTD)
def build_query_chart_1_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=1 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 1 — Provider Group Volume (ccd / volume / YOY)
def build_query_chart_1_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=1 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 2 — Provider Volume (ccd / volume / YTD)
def build_query_chart_2_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=2 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 2 — Provider Volume (ccd / volume / YOY)
def build_query_chart_2_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=2 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 3 — Gross Episode Spend (ccd / spend / YTD)
def build_query_chart_3_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=3 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 3 — Gross Episode Spend (ccd / spend / YOY)
def build_query_chart_3_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=3 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 4 — Gross Episode Counts (ccd / spend / YTD)
def build_query_chart_4_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=4 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 4 — Gross Episode Counts (ccd / spend / YOY)
def build_query_chart_4_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=4 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 5 — Medical Category Spend (ccd / spend / YTD)
def build_query_chart_5_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=5 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 5 — Medical Category Spend (ccd / spend / YOY)
def build_query_chart_5_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=5 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 6 — Pharmacy Category Spend (ccd / spend / YTD)
def build_query_chart_6_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=6 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 6 — Pharmacy Category Spend (ccd / spend / YOY)
def build_query_chart_6_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=6 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 7 — High-Cost Drugs Spend (ccd / spend / YTD)
def build_query_chart_7_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=7 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 7 — High-Cost Drugs Spend (ccd / spend / YOY)
def build_query_chart_7_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=7 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 8 — Per Episode Spend (ccd / spend / YTD)
def build_query_chart_8_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=8 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 8 — Per Episode Spend (ccd / spend / YOY)
def build_query_chart_8_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=8 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 9 — Member Visits (ccd / utilization / YTD)
def build_query_chart_9_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=9 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 9 — Member Visits (ccd / utilization / YOY)
def build_query_chart_9_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=9 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 10 — Client Visits (ccd / utilization / YTD)
def build_query_chart_10_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=10 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 10 — Client Visits (ccd / utilization / YOY)
def build_query_chart_10_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=10 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 11 — Claim Count (ccd / utilization / YTD)
def build_query_chart_11_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=11 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 11 — Claim Count (ccd / utilization / YOY)
def build_query_chart_11_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=11 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 12 — Claim Procedure Count (ccd / utilization / YTD)
def build_query_chart_12_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=12 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 12 — Claim Procedure Count (ccd / utilization / YOY)
def build_query_chart_12_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=12 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 13 — Gross Savings (ccd / savings / YTD)
def build_query_chart_13_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=13 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 13 — Gross Savings (ccd / savings / YOY)
def build_query_chart_13_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=13 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 14 — Episode Savings (ccd / savings / YTD)
def build_query_chart_14_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=14 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 14 — Episode Savings (ccd / savings / YOY)
def build_query_chart_14_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=14 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 15 — Groups Meeting Board Cert. Criteria (ccd / quality / YTD)
def build_query_chart_15_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=15 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 15 — Groups Meeting Board Cert. Criteria (ccd / quality / YOY)
def build_query_chart_15_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=15 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 16 — Providers having Board Certification (ccd / quality / YTD)
def build_query_chart_16_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=16 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 16 — Providers having Board Certification (ccd / quality / YOY)
def build_query_chart_16_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=16 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 17 — Groups Meeting External Quality Certification Criteria (ccd / quality / YTD)
def build_query_chart_17_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=17 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 17 — Groups Meeting External Quality Certification Criteria (ccd / quality / YOY)
def build_query_chart_17_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=17 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 18 — Providers having External Quality Certification (ccd / quality / YTD)
def build_query_chart_18_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=18 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 18 — Providers having External Quality Certification (ccd / quality / YOY)
def build_query_chart_18_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=18 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 19 — Groups Meeting EBM Criteria (ccd / quality / YTD)
def build_query_chart_19_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=19 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 19 — Groups Meeting EBM Criteria (ccd / quality / YOY)
def build_query_chart_19_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=19 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 20 — Providers having EBM Opportunities (ccd / quality / YTD)
def build_query_chart_20_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=20 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 20 — Providers having EBM Opportunities (ccd / quality / YOY)
def build_query_chart_20_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=20 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 21 — Provider Turnover (ccd / turnover-disruption / YTD)
def build_query_chart_21_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=21 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 21 — Provider Turnover (ccd / turnover-disruption / YOY)
def build_query_chart_21_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=21 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 22 — Member-to-Provider Relationships (ccd / turnover-disruption / YTD)
def build_query_chart_22_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=22 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 22 — Member-to-Provider Relationships (ccd / turnover-disruption / YOY)
def build_query_chart_22_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=22 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 101 — Provider Group Volume (tier-1 / volume / YTD)
def build_query_chart_101_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=101 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 101 — Provider Group Volume (tier-1 / volume / YOY)
def build_query_chart_101_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=101 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 102 — Provider Volume (tier-1 / volume / YTD)
def build_query_chart_102_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=102 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 102 — Provider Volume (tier-1 / volume / YOY)
def build_query_chart_102_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=102 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 103 — Gross Episode Spend (tier-1 / spend / YTD)
def build_query_chart_103_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=103 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 103 — Gross Episode Spend (tier-1 / spend / YOY)
def build_query_chart_103_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=103 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 104 — Gross Episode Counts (tier-1 / spend / YTD)
def build_query_chart_104_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=104 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 104 — Gross Episode Counts (tier-1 / spend / YOY)
def build_query_chart_104_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=104 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 105 — Medical Category Spend (tier-1 / spend / YTD)
def build_query_chart_105_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=105 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 105 — Medical Category Spend (tier-1 / spend / YOY)
def build_query_chart_105_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=105 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 106 — Pharmacy Category Spend (tier-1 / spend / YTD)
def build_query_chart_106_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=106 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 106 — Pharmacy Category Spend (tier-1 / spend / YOY)
def build_query_chart_106_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=106 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 107 — High-Cost Drugs Spend (tier-1 / spend / YTD)
def build_query_chart_107_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=107 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 107 — High-Cost Drugs Spend (tier-1 / spend / YOY)
def build_query_chart_107_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=107 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 108 — Per Episode Spend (tier-1 / spend / YTD)
def build_query_chart_108_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=108 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 108 — Per Episode Spend (tier-1 / spend / YOY)
def build_query_chart_108_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=108 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 109 — Member Visits (tier-1 / utilization / YTD)
def build_query_chart_109_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=109 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 109 — Member Visits (tier-1 / utilization / YOY)
def build_query_chart_109_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=109 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 110 — Client Visits (tier-1 / utilization / YTD)
def build_query_chart_110_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=110 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 110 — Client Visits (tier-1 / utilization / YOY)
def build_query_chart_110_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=110 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 111 — Claim Count (tier-1 / utilization / YTD)
def build_query_chart_111_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=111 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 111 — Claim Count (tier-1 / utilization / YOY)
def build_query_chart_111_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=111 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 112 — Claim Procedure Count (tier-1 / utilization / YTD)
def build_query_chart_112_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=112 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 112 — Claim Procedure Count (tier-1 / utilization / YOY)
def build_query_chart_112_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=112 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 113 — Gross Savings (tier-1 / savings / YTD)
def build_query_chart_113_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=113 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 113 — Gross Savings (tier-1 / savings / YOY)
def build_query_chart_113_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=113 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 114 — Episode Savings (tier-1 / savings / YTD)
def build_query_chart_114_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=114 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 114 — Episode Savings (tier-1 / savings / YOY)
def build_query_chart_114_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=114 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 115 — Groups Meeting Board Cert. Criteria (tier-1 / quality / YTD)
def build_query_chart_115_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=115 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 115 — Groups Meeting Board Cert. Criteria (tier-1 / quality / YOY)
def build_query_chart_115_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=115 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 116 — Providers having Board Certification (tier-1 / quality / YTD)
def build_query_chart_116_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=116 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 116 — Providers having Board Certification (tier-1 / quality / YOY)
def build_query_chart_116_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=116 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 117 — Groups Meeting External Quality Certification Criteria (tier-1 / quality / YTD)
def build_query_chart_117_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=117 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 117 — Groups Meeting External Quality Certification Criteria (tier-1 / quality / YOY)
def build_query_chart_117_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=117 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 118 — Providers having External Quality Certification (tier-1 / quality / YTD)
def build_query_chart_118_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=118 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 118 — Providers having External Quality Certification (tier-1 / quality / YOY)
def build_query_chart_118_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=118 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 119 — Groups Meeting EBM Criteria (tier-1 / quality / YTD)
def build_query_chart_119_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=119 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 119 — Groups Meeting EBM Criteria (tier-1 / quality / YOY)
def build_query_chart_119_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=119 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 120 — Providers having EBM Opportunities (tier-1 / quality / YTD)
def build_query_chart_120_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=120 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 120 — Providers having EBM Opportunities (tier-1 / quality / YOY)
def build_query_chart_120_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=120 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 121 — Provider Turnover (tier-1 / turnover-disruption / YTD)
def build_query_chart_121_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=121 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 121 — Provider Turnover (tier-1 / turnover-disruption / YOY)
def build_query_chart_121_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=121 (YOY). Replace this SQL when ready."""
    return _default_query(context)

# Chart 122 — Member-to-Provider Relationships (tier-1 / turnover-disruption / YTD)
def build_query_chart_122_ytd(context: ChartQueryContext) -> str:
    """SQL for chart_id=122 (YTD). Replace this SQL when ready."""
    return _default_query(context)

# Chart 122 — Member-to-Provider Relationships (tier-1 / turnover-disruption / YOY)
def build_query_chart_122_yoy(context: ChartQueryContext) -> str:
    """SQL for chart_id=122 (YOY). Replace this SQL when ready."""
    return _default_query(context)


QUERY_BUILDERS: dict[BuilderKey, QueryBuilder] = {
    ("1", "ytd"): build_query_chart_1_ytd,
    ("1", "yoy"): build_query_chart_1_yoy,
    ("2", "ytd"): build_query_chart_2_ytd,
    ("2", "yoy"): build_query_chart_2_yoy,
    ("3", "ytd"): build_query_chart_3_ytd,
    ("3", "yoy"): build_query_chart_3_yoy,
    ("4", "ytd"): build_query_chart_4_ytd,
    ("4", "yoy"): build_query_chart_4_yoy,
    ("5", "ytd"): build_query_chart_5_ytd,
    ("5", "yoy"): build_query_chart_5_yoy,
    ("6", "ytd"): build_query_chart_6_ytd,
    ("6", "yoy"): build_query_chart_6_yoy,
    ("7", "ytd"): build_query_chart_7_ytd,
    ("7", "yoy"): build_query_chart_7_yoy,
    ("8", "ytd"): build_query_chart_8_ytd,
    ("8", "yoy"): build_query_chart_8_yoy,
    ("9", "ytd"): build_query_chart_9_ytd,
    ("9", "yoy"): build_query_chart_9_yoy,
    ("10", "ytd"): build_query_chart_10_ytd,
    ("10", "yoy"): build_query_chart_10_yoy,
    ("11", "ytd"): build_query_chart_11_ytd,
    ("11", "yoy"): build_query_chart_11_yoy,
    ("12", "ytd"): build_query_chart_12_ytd,
    ("12", "yoy"): build_query_chart_12_yoy,
    ("13", "ytd"): build_query_chart_13_ytd,
    ("13", "yoy"): build_query_chart_13_yoy,
    ("14", "ytd"): build_query_chart_14_ytd,
    ("14", "yoy"): build_query_chart_14_yoy,
    ("15", "ytd"): build_query_chart_15_ytd,
    ("15", "yoy"): build_query_chart_15_yoy,
    ("16", "ytd"): build_query_chart_16_ytd,
    ("16", "yoy"): build_query_chart_16_yoy,
    ("17", "ytd"): build_query_chart_17_ytd,
    ("17", "yoy"): build_query_chart_17_yoy,
    ("18", "ytd"): build_query_chart_18_ytd,
    ("18", "yoy"): build_query_chart_18_yoy,
    ("19", "ytd"): build_query_chart_19_ytd,
    ("19", "yoy"): build_query_chart_19_yoy,
    ("20", "ytd"): build_query_chart_20_ytd,
    ("20", "yoy"): build_query_chart_20_yoy,
    ("21", "ytd"): build_query_chart_21_ytd,
    ("21", "yoy"): build_query_chart_21_yoy,
    ("22", "ytd"): build_query_chart_22_ytd,
    ("22", "yoy"): build_query_chart_22_yoy,
    ("101", "ytd"): build_query_chart_101_ytd,
    ("101", "yoy"): build_query_chart_101_yoy,
    ("102", "ytd"): build_query_chart_102_ytd,
    ("102", "yoy"): build_query_chart_102_yoy,
    ("103", "ytd"): build_query_chart_103_ytd,
    ("103", "yoy"): build_query_chart_103_yoy,
    ("104", "ytd"): build_query_chart_104_ytd,
    ("104", "yoy"): build_query_chart_104_yoy,
    ("105", "ytd"): build_query_chart_105_ytd,
    ("105", "yoy"): build_query_chart_105_yoy,
    ("106", "ytd"): build_query_chart_106_ytd,
    ("106", "yoy"): build_query_chart_106_yoy,
    ("107", "ytd"): build_query_chart_107_ytd,
    ("107", "yoy"): build_query_chart_107_yoy,
    ("108", "ytd"): build_query_chart_108_ytd,
    ("108", "yoy"): build_query_chart_108_yoy,
    ("109", "ytd"): build_query_chart_109_ytd,
    ("109", "yoy"): build_query_chart_109_yoy,
    ("110", "ytd"): build_query_chart_110_ytd,
    ("110", "yoy"): build_query_chart_110_yoy,
    ("111", "ytd"): build_query_chart_111_ytd,
    ("111", "yoy"): build_query_chart_111_yoy,
    ("112", "ytd"): build_query_chart_112_ytd,
    ("112", "yoy"): build_query_chart_112_yoy,
    ("113", "ytd"): build_query_chart_113_ytd,
    ("113", "yoy"): build_query_chart_113_yoy,
    ("114", "ytd"): build_query_chart_114_ytd,
    ("114", "yoy"): build_query_chart_114_yoy,
    ("115", "ytd"): build_query_chart_115_ytd,
    ("115", "yoy"): build_query_chart_115_yoy,
    ("116", "ytd"): build_query_chart_116_ytd,
    ("116", "yoy"): build_query_chart_116_yoy,
    ("117", "ytd"): build_query_chart_117_ytd,
    ("117", "yoy"): build_query_chart_117_yoy,
    ("118", "ytd"): build_query_chart_118_ytd,
    ("118", "yoy"): build_query_chart_118_yoy,
    ("119", "ytd"): build_query_chart_119_ytd,
    ("119", "yoy"): build_query_chart_119_yoy,
    ("120", "ytd"): build_query_chart_120_ytd,
    ("120", "yoy"): build_query_chart_120_yoy,
    ("121", "ytd"): build_query_chart_121_ytd,
    ("121", "yoy"): build_query_chart_121_yoy,
    ("122", "ytd"): build_query_chart_122_ytd,
    ("122", "yoy"): build_query_chart_122_yoy,
}


def build_query(context: ChartQueryContext) -> str:
    builder = resolve_query_builder(context, QUERY_BUILDERS, _default_query)
    return builder(context)


def build_ytd_query(context: ChartQueryContext) -> str:
    return build_query(context)


def build_yoy_query(context: ChartQueryContext) -> str:
    return build_query(context)


def registered_builder_keys() -> frozenset[BuilderKey]:
    return frozenset(QUERY_BUILDERS)


def has_dedicated_query(context: ChartQueryContext) -> bool:
    from features.fetch_charts.query_library.registry import builder_key

    key = builder_key(context)
    return key is not None and key in QUERY_BUILDERS
