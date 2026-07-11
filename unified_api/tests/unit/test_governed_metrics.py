"""Governed metric and citation tests."""

from unified_api.services.governed_metrics import (
    append_citation_section,
    build_citations,
    metric_limitation,
)


def test_upfront_is_not_substituted_with_total_value():
    limitation = metric_limitation("Deals with disclosed upfront over $100M")

    assert "not available" in limitation
    assert "will not substitute" in limitation


def test_aggregate_results_receive_query_provenance():
    citations = build_citations("sql", [{"deal_count": 23}], "SELECT COUNT(*)")

    assert citations[0]["source"] == "Cortellis"
    assert citations[0]["record_type"] == "aggregate_query"
    assert citations[0]["query_fingerprint"]


def test_record_results_receive_stable_source_ids():
    citations = build_citations("rag", [{
        "deal_id": 42,
        "contract_id": 7,
        "deal_title": "Example deal",
    }])

    assert citations[0]["id"] == "C1"
    assert citations[0]["record_id"] == 7
    assert "[C1]" in append_citation_section("Answer", citations)
