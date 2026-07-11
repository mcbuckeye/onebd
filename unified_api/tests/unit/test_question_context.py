"""Question grounding and entity-context regression tests."""

import pytest

from unified_api.routers.chat import (
    _build_governed_sql,
    _missing_resolved_entity_ids,
    _structured_metric_limitation,
)
from unified_api.services.llm import LLMService
from unified_api.services.question_context import (
    extract_company_phrases,
    resolve_company_mentions,
)


def test_extracts_company_mentions_without_domain_terms():
    assert extract_company_phrases(
        "Compare Pfizer vs Merck in oncology ADC deals"
    ) == ["Pfizer", "Merck"]


def test_resolves_legal_suffix_to_canonical_company_id():
    def search(phrase, limit):
        assert phrase == "Pfizer"
        assert limit == 5
        return [{
            "id": 18767,
            "name": "Pfizer Inc",
            "ticker": "PFE",
            "similarity": 0.8,
        }]

    assert resolve_company_mentions(
        "How many deals did Pfizer do in 2024?",
        search=search,
    ) == [{
        "mention": "Pfizer",
        "status": "resolved",
        "company_id": 18767,
        "canonical_name": "Pfizer Inc",
        "ticker": "PFE",
    }]


def test_prefers_ticker_backed_parent_over_suffix_duplicates():
    def search(phrase, limit):
        return [
            {"id": 18767, "name": "Pfizer Inc", "ticker": "PFE", "has_xref": True},
            {"id": 18862, "name": "Pfizer Ltd", "ticker": None, "has_xref": False},
        ]

    result = resolve_company_mentions("Pfizer deals", search=search)

    assert result[0]["status"] == "resolved"
    assert result[0]["company_id"] == 18767


def test_resolution_preserves_reviewable_parent_relationship():
    def search(phrase, limit):
        return [{
            "id": 18862,
            "name": "Pfizer Ltd",
            "ticker": None,
            "has_xref": True,
            "parent_company_id": 18767,
            "parent_company_name": "Pfizer Inc",
            "relationship_type": "subsidiary",
        }]

    result = resolve_company_mentions("Pfizer Ltd deals", search=search)

    assert result[0]["company_id"] == 18862
    assert result[0]["parent_company_id"] == 18767
    assert result[0]["relationship_type"] == "subsidiary"


def test_milestone_analytics_does_not_substitute_total_value():
    limitation = _structured_metric_limitation(
        "What is the median milestone payment for Phase 3 license deals?"
    )

    assert "not available" in limitation
    assert "not substitute" in limitation


def test_generated_sql_must_use_resolved_company_id():
    entities = [{"status": "resolved", "company_id": 18767}]

    assert _missing_resolved_entity_ids(
        "SELECT COUNT(*) FROM deal_companies WHERE company_id = 18767",
        entities,
    ) == []
    assert _missing_resolved_entity_ids(
        "SELECT COUNT(*) FROM companies WHERE name ILIKE 'Pfizer'",
        entities,
    ) == [18767]


def test_company_year_deal_count_uses_governed_sql():
    sql = _build_governed_sql(
        "How many deals did Pfizer do in 2024?",
        [{"status": "resolved", "company_id": 18767}],
    )

    assert "COUNT(DISTINCT d.id) AS deal_count" in sql
    assert "dc.company_id = 18767" in sql
    assert "2024-01-01" in sql
    assert "2025-01-01" in sql


@pytest.mark.asyncio
async def test_empty_synthesis_is_deterministic_and_grounded():
    service = object.__new__(LLMService)

    result = await service.synthesize_response("What is Roche's strategy?", "sql", [])

    assert result["confidence"]["evidence_status"] == "insufficient"
    assert "cannot provide a reliable answer" in result["answer"]


@pytest.mark.asyncio
async def test_null_aggregate_is_insufficient_evidence():
    service = object.__new__(LLMService)

    result = await service.synthesize_response(
        "Median milestone payment?",
        "sql",
        [{"median_milestone_payment": None}],
    )

    assert result["confidence"]["evidence_status"] == "insufficient"
