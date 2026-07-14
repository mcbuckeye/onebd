"""Question grounding and entity-context regression tests."""

import pytest

from unified_api.routers.chat import (
    _build_governed_sql,
    _is_deal_pattern_query,
    _missing_resolved_entity_ids,
    _structured_metric_limitation,
)
from unified_api.services.llm import LLMService, _financial_disclosure_summary
from unified_api.services.question_context import (
    extract_company_phrases,
    resolve_company_mentions,
    resolve_drug_mentions,
)


def test_extracts_company_mentions_without_domain_terms():
    assert extract_company_phrases(
        "Compare Pfizer vs Merck in oncology ADC deals"
    ) == ["Pfizer", "Merck"]


def test_valuation_domain_term_is_not_resolved_as_a_company():
    assert extract_company_phrases(
        "Valuation range for oncology M&A deals, 2020–2025?"
    ) == []


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


def test_prefers_ticker_backed_holding_company_for_short_brand_name():
    def search(phrase, limit):
        assert phrase == "Roche"
        return [
            {
                "id": 19446,
                "name": "Roche Holding Ltd",
                "ticker": "RHHBY",
                "has_xref": True,
            },
            {
                "id": 19450,
                "name": "Roche AG",
                "ticker": None,
                "has_xref": False,
            },
        ]

    result = resolve_company_mentions("Roche oncology strategy", search=search)

    assert result[0]["status"] == "resolved"
    assert result[0]["company_id"] == 19446
    assert result[0]["canonical_name"] == "Roche Holding Ltd"


def test_compound_holding_suffix_normalizes_independent_of_legal_form():
    from unified_api.services.entity_resolution import EntityResolutionService

    service = object.__new__(EntityResolutionService)

    assert service.normalize_company_name("Roche Holding Ltd") == "ROCHE"
    assert service.normalize_company_name("Roche Holdings AG") == "ROCHE"


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


def test_resolves_exact_source_backed_drug_alias():
    def search(question, limit):
        assert question == "What targets does Adenoscan have?"
        assert limit == 5
        return [{
            "drug_id": 2428,
            "name_display": "Adenoscan",
            "matched_alias": "Adenoscan",
            "match_source": "cortellis",
        }]

    assert resolve_drug_mentions(
        "What targets does Adenoscan have?",
        search=search,
    ) == [{
        "entity_type": "drug",
        "mention": "Adenoscan",
        "status": "resolved",
        "drug_id": 2428,
        "canonical_name": "Adenoscan",
        "match_source": "cortellis",
    }]


def test_shared_drug_alias_requires_disambiguation():
    def search(_question, _limit):
        return [
            {
                "drug_id": 11,
                "name_display": "Asset formulation A",
                "matched_alias": "Examplemab",
            },
            {
                "drug_id": 12,
                "name_display": "Asset formulation B",
                "matched_alias": "Examplemab",
            },
        ]

    result = resolve_drug_mentions("Trials for Examplemab", search=search)

    assert result[0]["status"] == "ambiguous"
    assert [item["drug_id"] for item in result[0]["candidates"]] == [11, 12]


def test_drug_alias_must_have_word_boundaries():
    def search(_question, _limit):
        return [{
            "drug_id": 2428,
            "name_display": "Adenoscan",
            "matched_alias": "Adenoscan",
        }]

    assert resolve_drug_mentions("Adenoscanlike target", search=search) == []


def test_governed_milestone_analytics_is_not_refused():
    limitation = _structured_metric_limitation(
        "What is the median milestone payment for Phase 3 license deals?"
    )

    assert limitation is None
    sql = _build_governed_sql(
        "What is the median milestone payment for Phase 3 license deals?",
        [],
    )
    assert "deal_financial_terms" in sql
    assert "term_type = 'milestone_total'" in sql
    assert "phase_highest_start = 'Phase 3 Clinical'" in sql


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


def test_generated_sql_must_use_resolved_drug_id():
    entities = [{"status": "resolved", "drug_id": 2428}]

    assert _missing_resolved_entity_ids(
        "SELECT * FROM public_drug_target_links WHERE drug_id = 2428",
        entities,
    ) == []
    assert _missing_resolved_entity_ids(
        "SELECT * FROM public_drug_target_links",
        entities,
    ) == [2428]


@pytest.mark.parametrize(
    ("question", "required_sql"),
    [
        ("What trials are linked to Adenoscan?", "trial.nct_id"),
        ("What targets does Adenoscan have?", "target.ensembl_id"),
        ("What diseases are linked to Adenoscan?", "disease.disease_id"),
    ],
)
def test_drug_public_evidence_questions_use_exact_governed_links(
    question,
    required_sql,
):
    sql = _build_governed_sql(question, [{
        "entity_type": "drug",
        "status": "resolved",
        "drug_id": 2428,
    }])

    assert required_sql in sql
    assert "2428" in sql
    assert "LIMIT 20" in sql


def test_target_to_drug_question_uses_exact_symbol_and_link_table():
    sql = _build_governed_sql("Which drugs target EGFR?", [])

    assert "public_drug_target_links" in sql
    assert "UPPER(target.approved_symbol) = 'EGFR'" in sql
    assert "drug.id AS drug_id" in sql


def test_company_year_deal_count_uses_governed_sql():
    sql = _build_governed_sql(
        "How many deals did Pfizer do in 2024?",
        [{"status": "resolved", "company_id": 18767}],
    )

    assert "COUNT(DISTINCT d.id) AS deal_count" in sql
    assert "dc.company_id = 18767" in sql
    assert "2024-01-01" in sql
    assert "2025-01-01" in sql


def test_company_oncology_strategy_uses_governed_deal_pattern_sql():
    question = "What is Roche's oncology strategy from its deal pattern?"
    sql = _build_governed_sql(
        question,
        [{"status": "resolved", "company_id": 19446}],
    )

    assert _is_deal_pattern_query(question)
    assert "dc.company_id = 19446" in sql
    assert "ta.name = 'Cancer'" in sql
    assert "GROUP BY COALESCE(d.agreement_type, 'Unknown')" in sql


@pytest.mark.parametrize(
    ("question", "required_sql"),
    [
        ("Who are the top 5 most active acquirers this year?", "dc.role = 'Partner'"),
        ("What is the average deal size in oncology?", "ta.name = 'Cancer'"),
        ("Valuation range for oncology M&A deals, 2020–2025?", "d.agreement_type = 'Company - M&A"),
        ("How have deal values trended over five years?", "INTERVAL '5 years'"),
        ("Percentage of 2024 deals that were M&A vs licensing.", "ILIKE '%License%'"),
        ("Who is most actively acquiring oncology assets?", "ta.name = 'Cancer'"),
        ("Top 20 largest pharma deals ever.", "LIMIT 20"),
        ("Deal-activity heatmap by therapy area.", "GROUP BY ta.name"),
        ("Deal volume by geography.", "JOIN territories t"),
    ],
)
def test_high_value_questions_use_governed_sql(question, required_sql):
    sql = _build_governed_sql(question, [])

    assert sql is not None
    assert required_sql in sql


def test_financial_governed_sql_normalizes_currency_and_unit():
    sql = _build_governed_sql("What is the average deal size in oncology?", [])

    assert "total_projected_current_currency = 'USD'" in sql
    assert "total_projected_current_unit = 'Million'" in sql


@pytest.mark.parametrize(
    ("question", "required_fragments"),
    [
        (
            "Typical upfront payments for Phase 2 ADC assets?",
            (
                "term_type = 'upfront_payment'",
                "phase_highest_start = 'Phase 2 Clinical'",
                "technology.name = 'Antibody drug conjugate'",
                "median_upfront_usd_millions",
            ),
        ),
        (
            "Typical royalty rates for oncology bispecifics?",
            (
                "term_type = 'royalty_rate'",
                "therapy.name = 'Cancer'",
                "technology.name ILIKE 'Bispecific%'",
                "median_royalty_midpoint_pct",
            ),
        ),
        (
            "Deals with disclosed upfront over $100M.",
            (
                "term_type = 'upfront_payment'",
                "upfront_usd_millions > 100",
                "deal.id AS deal_id",
                "deal.agreement_type ILIKE '%License%'",
                "LIMIT 20",
            ),
        ),
    ],
)
def test_financial_term_questions_use_release_gated_queries(
    question,
    required_fragments,
):
    sql = _build_governed_sql(question, [])

    assert sql is not None
    for fragment in required_fragments:
        assert fragment in sql
    assert "basis = 'projected_current'" in sql
    assert "parser_version = 4" in sql
    assert "NOT term.is_breakdown" in sql


def test_ma_governed_sql_uses_agreement_type_not_empty_deal_type():
    sql = _build_governed_sql(
        "Valuation range for oncology M&A deals, 2020–2025?",
        [],
    )

    assert "agreement_type" in sql
    assert "deal_type" not in sql


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


def test_aggregate_financial_disclosure_uses_underlying_deal_counts():
    assert _financial_disclosure_summary([{
        "disclosed_deal_count": 14,
        "eligible_deal_count": 22,
    }]) == (63.6, 14)


def test_financial_listing_disclosure_counts_populated_term_rows():
    assert _financial_disclosure_summary([
        {"deal_id": 1, "upfront_usd_millions": 125.0},
        {"deal_id": 2, "upfront_usd_millions": 200.0},
    ]) == (100.0, 2)
