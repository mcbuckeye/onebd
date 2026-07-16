"""Regression tests for governed Agentic RAG examples."""

from datetime import datetime

import pytest

from unified_api.routers import agentic_rag
from unified_api.services.agentic_rag.models import ToolResult


@pytest.mark.asyncio
async def test_builtin_adc_example_uses_structured_financial_query(monkeypatch):
    class FakeTool:
        async def execute(self, query: str):
            assert "deal_finance_summary" in query
            assert "deal_technologies" in query
            assert "therapy.name = 'Cancer'" in query
            return ToolResult(
                success=True,
                data=[{
                    "id": 1,
                    "title": "Example ADC license",
                    "status": "Active",
                    "date_start": "2026-01-01",
                    "adc_technologies": "Antibody-drug conjugate",
                    "total_value_usd_millions": 500.0,
                    "eligible_deal_count": 10,
                    "disclosed_deal_count": 4,
                }],
                row_count=1,
                query_executed=query,
            )

    monkeypatch.setattr(agentic_rag, "_get_sql_tool", lambda: FakeTool())

    response = await agentic_rag._governed_agentic_response(
        "Find oncology deals involving ADCs with disclosed values",
        started_at=datetime.utcnow(),
    )

    assert response is not None
    assert response.success is True
    assert response.total_hops == 1
    assert "Example ADC license" in response.answer
    assert "deal_finance_summary" in response.reasoning_steps[0].query
