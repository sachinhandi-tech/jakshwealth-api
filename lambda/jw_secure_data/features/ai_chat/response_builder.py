"""Map query rows into UI-ready AI chat payloads."""

from __future__ import annotations

from typing import Any

from services.llm.types import LlmQueryPlan

JSON = dict[str, Any]


def build_chat_response(plan: LlmQueryPlan, rows: list[JSON]) -> JSON:
    if plan.response_type == "text":
        return {
            "responseType": "text",
            "content": plan.text or "",
        }
    if plan.response_type == "table":
        return _build_table_response(plan, rows)
    return _build_chart_response(plan, rows)


def _build_table_response(plan: LlmQueryPlan, rows: list[JSON]) -> JSON:
    presentation = plan.presentation or {}
    columns = presentation.get("columns")
    if not isinstance(columns, list) or not columns:
        columns = _columns_from_rows(rows)
    return {
        "responseType": "table",
        "title": presentation.get("title"),
        "columns": columns,
        "rows": rows,
    }


def _build_chart_response(plan: LlmQueryPlan, rows: list[JSON]) -> JSON:
    presentation = plan.presentation or {}
    labels_column = str(presentation.get("labelsColumn") or "")
    data_column = str(presentation.get("dataColumn") or "")
    labels = [str(row.get(labels_column, "")) for row in rows] if labels_column else []
    data = [_coerce_number(row.get(data_column)) for row in rows] if data_column else []

    chart_type = str(presentation.get("chartType") or "bar")
    payload: JSON = {
        "responseType": "chart",
        "chartType": chart_type,
        "chartId": presentation.get("chartId") or "ai-chat-chart",
        "title": presentation.get("title") or "Chart",
        "labels": labels,
        "data": data,
    }
    if presentation.get("explanation"):
        payload["explanation"] = presentation["explanation"]

    if chart_type == "doughnut":
        payload["centerLines"] = _render_center_lines(
            presentation.get("centerLines"),
            rows=rows,
            labels_column=labels_column,
            data_column=data_column,
        )
        payload["hoverMessages"] = _render_hover_messages(
            presentation.get("hoverMessages"),
            rows=rows,
            labels_column=labels_column,
            data_column=data_column,
        )
    return payload


def _columns_from_rows(rows: list[JSON]) -> list[JSON]:
    if not rows:
        return []
    return [{"key": key, "label": _labelize(key)} for key in rows[0]]


def _labelize(key: str) -> str:
    return key.replace("_", " ").strip().title()


def _coerce_number(value: Any) -> float | int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if value is None:
        return 0
    return float(value)


def _render_center_lines(
    templates: Any,
    *,
    rows: list[JSON],
    labels_column: str,
    data_column: str,
) -> list[str]:
    if not isinstance(templates, list):
        return []
    primary_value = rows[0].get(data_column) if rows else 0
    total = sum(_coerce_number(row.get(data_column)) for row in rows)
    context = {
        "primary_value": _format_compact(primary_value),
        "total": _format_compact(total),
    }
    return [_apply_tokens(str(line), context) for line in templates]


def _render_hover_messages(
    templates: Any,
    *,
    rows: list[JSON],
    labels_column: str,
    data_column: str,
) -> list[str]:
    if not isinstance(templates, list) or not templates:
        return []
    template = str(templates[0])
    messages: list[str] = []
    for row in rows:
        context = {
            "label": str(row.get(labels_column, "")),
            "value": _format_compact(row.get(data_column)),
        }
        messages.append(_apply_tokens(template, context))
    return messages


def _apply_tokens(template: str, context: dict[str, str]) -> str:
    rendered = template
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def _format_compact(value: Any) -> str:
    number = _coerce_number(value)
    absolute = abs(int(number)) if float(number).is_integer() else abs(float(number))
    if absolute >= 1_000_000:
        millions = absolute / 1_000_000
        return f"{int(millions)}M" if float(millions).is_integer() else f"{millions:.1f}M"
    if absolute >= 1_000:
        thousands = absolute / 1_000
        return f"{int(thousands)}K" if float(thousands).is_integer() else f"{thousands:.1f}K"
    if float(number).is_integer():
        return f"{int(number):,}"
    return f"{float(number):,.2f}"
