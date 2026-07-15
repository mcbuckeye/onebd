"""
TDD: Chat v2 synthesis tests — write these FIRST, then implement.
"""
from unittest.mock import AsyncMock

class TestFollowUpSuggestions:
    """Test contextual follow-up generation."""

    def test_company_query_gets_company_followups(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("What deals has Pfizer done?")
        assert len(suggestions) > 0
        assert len(suggestions) <= 3
        assert all(isinstance(s, str) for s in suggestions)

    def test_oncology_query_gets_oncology_followups(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("Show me oncology deal trends")
        assert len(suggestions) > 0
        assert len(suggestions) <= 3

    def test_modality_query_gets_modality_followups(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("ADC deals in solid tumors")
        assert len(suggestions) > 0

    def test_valuation_query_gets_financial_followups(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("What are typical upfront values?")
        assert len(suggestions) > 0

    def test_generic_query_gets_default_followups(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("hello world")
        assert len(suggestions) == 3  # always returns 3 defaults

    def test_followups_are_unique(self):
        from unified_api.services.llm import _suggest_follow_ups
        suggestions = _suggest_follow_ups("Pfizer oncology deals")
        assert len(suggestions) == len(set(suggestions))


def test_due_diligence_intent_is_detected_deterministically():
    from unified_api.routers.chat import _is_due_diligence_query

    assert _is_due_diligence_query("Full DD on Pfizer")
    assert _is_due_diligence_query("Generate a due diligence package for Pfizer")
    assert _is_due_diligence_query("DD report on Pfizer")
    assert not _is_due_diligence_query("How many deals has Pfizer completed?")


def test_common_governed_questions_bypass_llm_intent_classification():
    from unified_api.routers.chat import _is_governed_sql_query

    assert _is_governed_sql_query("What are the largest ADC deals in oncology?")
    assert _is_governed_sql_query(
        "Which companies are most actively acquiring oncology assets?"
    )
    assert _is_governed_sql_query(
        "Which acquirers have done the most oncology deals?"
    )
    assert not _is_governed_sql_query("Search contract indemnification language")


async def test_chat_v2_governed_sql_uses_only_final_synthesis(monkeypatch):
    from unified_api.routers import chat

    llm = type("LLM", (), {})()
    llm.classify_intent = AsyncMock(return_value="deal_search")
    llm.synthesize_response = AsyncMock(return_value={
        "answer": "Grounded answer",
        "confidence": {"sample_size": 1},
        "follow_ups": [],
    })
    llm.format_response = AsyncMock(return_value="discarded formatting")
    raw = chat.ChatResponse(
        response="",
        mode_used="sql",
        sql_query="SELECT 1",
        data=[{"deal_id": 1}],
        citations=[{
            "id": "C1",
            "source": "Cortellis",
            "label": "Deal 1",
        }],
    )

    monkeypatch.setattr(
        "unified_api.services.llm.get_llm_service",
        lambda: llm,
    )
    handler = AsyncMock(return_value=raw)
    monkeypatch.setattr(chat, "_handle_sql_query", handler)

    response = await chat.chat_v2(chat.ChatRequest(
        message="What are the largest ADC deals in oncology?"
    ))

    llm.classify_intent.assert_not_awaited()
    llm.format_response.assert_not_awaited()
    llm.synthesize_response.assert_awaited_once()
    assert handler.await_args.kwargs["format_answer"] is False
    assert response.answer.startswith("Grounded answer")


async def test_due_diligence_chat_uses_governed_package():
    from unified_api.routers.chat import _handle_due_diligence_query

    async def generator(company_id):
        assert company_id == 42
        return {
            "company": {"id": 42, "name": "Example Bio"},
            "metadata": {"financial_disclosure_rate": "40.0%"},
            "sections": [
                {
                    "type": "company_overview",
                    "title": "Company Overview",
                    "content": {"total_deals": 10},
                    "status": "available",
                    "source": "Cortellis Deals",
                },
                {
                    "type": "sec_filings",
                    "title": "SEC Filings",
                    "content": [{
                        "id": 9,
                        "title": "Current report",
                        "source_url": "https://www.sec.gov/example",
                    }],
                    "status": "available",
                    "source": "SEC EDGAR",
                    "coverage": {"returned_filings": 1},
                },
                {
                    "type": "contracts",
                    "title": "Key Contracts",
                    "content": [{"deal_id": 100, "deal_title": "License"}],
                    "status": "available",
                    "source": "Cortellis contract metadata",
                    "coverage": {"returned_contracts": 1},
                },
                {
                    "type": "territory_rights",
                    "title": "Territory Rights",
                    "content": [{"deal_id": 100, "territory": "United States"}],
                    "status": "available",
                    "source": "Cortellis territory scope",
                    "coverage": {"returned_scope_records": 1},
                },
                {
                    "type": "comparable_transactions",
                    "title": "Comparable Transactions",
                    "content": [{"id": 200, "title": "Peer License"}],
                    "status": "available",
                    "source": "Cortellis Deals",
                    "coverage": {
                        "total_comparable_candidates": 25,
                        "returned_comparables": 1,
                    },
                },
            ],
        }

    response = await _handle_due_diligence_query(
        "Full DD on Example Bio",
        resolver=lambda _message: [{
            "mention": "Example Bio",
            "status": "resolved",
            "company_id": 42,
            "canonical_name": "Example Bio",
        }],
        generator=generator,
    )

    assert response.mode_used == "due_diligence"
    assert "10 Cortellis deals" in response.response
    assert "territory-scope records" in response.response
    assert len(response.data) == 5
    assert response.data[-1]["total_available"] == 25
    assert response.citations[0]["source"] == "SEC EDGAR"
    assert any(citation["record_id"] == 100 for citation in response.citations)


async def test_due_diligence_chat_requires_one_resolved_company():
    from unified_api.routers.chat import _handle_due_diligence_query

    response = await _handle_due_diligence_query(
        "Generate a DD package",
        resolver=lambda _message: [],
    )

    assert response.data == []
    assert "one specific company" in response.response
