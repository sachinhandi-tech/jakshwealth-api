#!/usr/bin/env python3
"""Regenerate chart_registry.py and queries.py from the chart catalog."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

LIBRARY_DIR = Path(__file__).resolve().parent
REGISTRY_OUTPUT = LIBRARY_DIR / "chart_registry.py"
QUERIES_OUTPUT = LIBRARY_DIR / "queries.py"
DEFAULT_DASHBOARD = "proof-points"
TIMELINES = ("ytd", "yoy")

_catalog_path = LIBRARY_DIR.parent / "chart_catalog.py"
_spec = importlib.util.spec_from_file_location("fetch_charts_chart_catalog", _catalog_path)
assert _spec and _spec.loader
_catalog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_catalog)
CHARTS = _catalog.CHART_CATALOG


def _build_registry_tree() -> dict:
    tree: dict = {}
    for chart_id, designation, view, _chart_type, name in CHARTS:
        tree.setdefault(DEFAULT_DASHBOARD, {})
        tree[DEFAULT_DASHBOARD].setdefault(designation, {})
        tree[DEFAULT_DASHBOARD][designation].setdefault(view, {})
        for timeline in TIMELINES:
            tree[DEFAULT_DASHBOARD][designation][view].setdefault(timeline, {})
            tree[DEFAULT_DASHBOARD][designation][view][timeline][name] = chart_id
    return tree


def _registry_py(tree: dict) -> str:
    body = json.dumps(tree, indent=4, sort_keys=True)
    body = body.replace(": true", ": True").replace(": false", ": False").replace(": null", ": None")
    return f'''\
"""Nested chart layout: dashboard → tier → view → timeline → chart name → chart_id.

Auto-generated from ``view_catalog.CHART_CATALOG``. SQL builders are keyed by
stable ``chart_id`` + timeline so metadata display-name changes do not break lookup.

Regenerate::

    python3 generate_queries_file.py
"""

from __future__ import annotations

CHART_REGISTRY: dict[str, dict[str, dict[str, dict[str, dict[str, str]]]]] = {body}
'''


HEADER = '''\
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
    value_rows = ",\\n    ".join(rows)
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
    value_rows = ",\\n    ".join(rows)
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


'''


FOOTER = """

QUERY_BUILDERS: dict[BuilderKey, QueryBuilder] = {
__BUILDER_ENTRIES__
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
"""


def _chart_section(chart_id: str, designation: str, view: str, timeline: str, name: str) -> str:
    safe_name = name.replace('"', '\\"')
    fn = f"build_query_chart_{chart_id}_{timeline}"
    return f'''
# Chart {chart_id} — {safe_name} ({designation} / {view} / {timeline.upper()})
def {fn}(context: ChartQueryContext) -> str:
    """SQL for chart_id={chart_id} ({timeline.upper()}). Replace this SQL when ready."""
    return _default_query(context)
'''


def main() -> None:
    tree = _build_registry_tree()
    REGISTRY_OUTPUT.write_text(_registry_py(tree), encoding="utf-8")

    sections: list[str] = []
    entries: list[str] = []
    for chart_id, designation, view, _chart_type, name in CHARTS:
        for timeline in TIMELINES:
            fn = f"build_query_chart_{chart_id}_{timeline}"
            sections.append(_chart_section(chart_id, designation, view, timeline, name))
            entries.append(f'    ("{chart_id}", "{timeline}"): {fn},')

    queries_content = HEADER + "".join(sections) + FOOTER.replace(
        "__BUILDER_ENTRIES__", "\n".join(entries)
    )
    QUERIES_OUTPUT.write_text(queries_content, encoding="utf-8")
    print(f"Wrote {REGISTRY_OUTPUT}")
    print(f"Wrote {QUERIES_OUTPUT} ({len(CHARTS)} charts x {len(TIMELINES)} timelines)")


if __name__ == "__main__":
    main()
