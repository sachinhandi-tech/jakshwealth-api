"""Deterministic LLM stand-in for local development and automated tests."""

from __future__ import annotations

from services.llm.types import LlmChatRequest, LlmChatResponse, LlmQueryPlan

_PROVIDER = "mock"
_MODEL = "mock-jw-planner-v1"

_CLAIMS_BY_REGION_DSL = {
    "from": {"table": "claims", "alias": "c"},
    "joins": [
        {
            "type": "left",
            "table": "members",
            "alias": "m",
            "on": {"left": "c.member_id", "op": "eq", "right": "m.member_id"},
        }
    ],
    "select": [
        {"field": "m.region", "as": "region"},
        {"agg": "count", "field": "c.claim_id", "as": "claim_count"},
        {"agg": "sum", "field": "c.paid_amount", "as": "total_paid"},
    ],
    "where": {"field": "c.claim_status", "op": "eq", "value": "PAID"},
    "group_by": ["m.region"],
    "order_by": [{"field": "claim_count", "kind": "alias", "dir": "desc"}],
    "limit": 100,
}

_RECENT_CLAIMS_DSL = {
    "from": {"table": "claims", "alias": "c"},
    "joins": [
        {
            "type": "left",
            "table": "members",
            "alias": "m",
            "on": {"left": "c.member_id", "op": "eq", "right": "m.member_id"},
        },
        {
            "type": "left",
            "table": "providers",
            "alias": "p",
            "on": {"left": "c.provider_id", "op": "eq", "right": "p.provider_id"},
        },
    ],
    "select": [
        {"field": "c.claim_id", "as": "claim_id"},
        {"field": "m.member_name", "as": "member_name"},
        {"field": "p.provider_name", "as": "provider_name"},
        {"field": "c.claim_status", "as": "claim_status"},
        {"field": "c.service_date", "as": "service_date"},
        {"field": "c.paid_amount", "as": "paid_amount"},
    ],
    "where": {"field": "c.claim_status", "op": "eq", "value": "PAID"},
    "order_by": [{"field": "c.service_date", "dir": "desc"}],
    "limit": 50,
}

_REGION_SAMPLE_ROWS = [
    {"region": "North", "claim_count": 420, "total_paid": 182_500},
    {"region": "South", "claim_count": 360, "total_paid": 149_200},
    {"region": "East", "claim_count": 295, "total_paid": 121_750},
]

_CLAIMS_TABLE_ROWS = [
    {
        "claim_id": "CLM-1001",
        "member_name": "Alex Smith",
        "provider_name": "City Care Clinic",
        "claim_status": "PAID",
        "service_date": "2026-03-12",
        "paid_amount": 245.5,
    },
    {
        "claim_id": "CLM-1002",
        "member_name": "Jordan Lee",
        "provider_name": "Northside Health",
        "claim_status": "PAID",
        "service_date": "2026-03-10",
        "paid_amount": 980.0,
    },
]


class MockLlmService:
    """Keyword-driven planner that mirrors the remote provider contract."""

    provider_name = _PROVIDER

    def complete(self, request: LlmChatRequest) -> LlmChatResponse:
        prompt = (request.prompt or "").strip().lower()
        if _is_text_prompt(prompt):
            plan = LlmQueryPlan(
                response_type="text",
                text=(
                    "I can answer questions about claims, members, and providers. "
                    "Ask for a table of recent claims or a chart of claims by region."
                ),
            )
            return LlmChatResponse(plan=plan, provider=self.provider_name, model=_MODEL)

        if _is_table_prompt(prompt):
            plan = LlmQueryPlan(
                response_type="table",
                dsl=dict(_RECENT_CLAIMS_DSL),
                presentation={
                    "title": "Recent paid claims",
                    "columns": [
                        {"key": "claim_id", "label": "Claim ID"},
                        {"key": "member_name", "label": "Member"},
                        {"key": "provider_name", "label": "Provider"},
                        {"key": "claim_status", "label": "Status"},
                        {"key": "service_date", "label": "Service date"},
                        {"key": "paid_amount", "label": "Paid amount"},
                    ],
                },
                sample_rows=list(_CLAIMS_TABLE_ROWS),
            )
            return LlmChatResponse(plan=plan, provider=self.provider_name, model=_MODEL)

        chart_type = "doughnut" if "doughnut" in prompt or "pie" in prompt else "bar"
        plan = LlmQueryPlan(
            response_type="chart",
            dsl=dict(_CLAIMS_BY_REGION_DSL),
            presentation={
                "chartType": chart_type,
                "chartId": "claims-by-region",
                "title": "Paid claims by region",
                "explanation": "Count of paid claims grouped by member region",
                "labelsColumn": "region",
                "dataColumn": "claim_count",
                "centerLines": ["{{primary_value}}", "top region", "out of {{total}}"],
                "hoverMessages": ["{{label}}\\n{{value}} claims"],
            },
            sample_rows=list(_REGION_SAMPLE_ROWS),
        )
        return LlmChatResponse(plan=plan, provider=self.provider_name, model=_MODEL)


def _is_text_prompt(prompt: str) -> bool:
    return any(token in prompt for token in ("hello", "help", "what can you"))


def _is_table_prompt(prompt: str) -> bool:
    return any(token in prompt for token in ("table", "list", "rows", "recent claims"))
