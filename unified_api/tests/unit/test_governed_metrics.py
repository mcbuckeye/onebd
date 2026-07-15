"""Governed metric and citation tests."""

from unified_api.services.governed_metrics import (
    append_citation_section,
    build_citations,
    metric_limitation,
)


def test_upfront_is_not_substituted_with_total_value():
    limitation = metric_limitation("What was the upfront for an unspecified deal?")

    assert "available" in limitation
    assert "will not" in limitation


def test_governed_upfront_listing_is_not_refused():
    assert metric_limitation("Deals with disclosed upfront over $100M") is None


def test_aggregate_results_receive_query_provenance():
    citations = build_citations("sql", [{"deal_count": 23}], "SELECT COUNT(*)")

    assert citations[0]["source"] == "Cortellis"
    assert citations[0]["record_type"] == "aggregate_query"
    assert citations[0]["query_fingerprint"]


def test_ranked_entity_ids_are_not_mislabeled_as_deal_citations():
    citations = build_citations(
        "sql",
        [
            {"id": 18077, "name": "Merck & Co Inc", "deal_count": 15},
            {"id": 19446, "name": "Roche Holding Ltd", "deal_count": 15},
        ],
        "SELECT c.id, c.name, COUNT(DISTINCT d.id) AS deal_count",
    )

    assert citations == [{
        "id": "C1",
        "source": "Cortellis",
        "record_type": "aggregate_query",
        "record_count": 2,
        "query_fingerprint": citations[0]["query_fingerprint"],
        "label": "Cortellis aggregate result",
    }]


def test_record_results_receive_stable_source_ids():
    citations = build_citations("rag", [{
        "deal_id": 42,
        "contract_id": 7,
        "deal_title": "Example deal",
    }])

    assert citations[0]["id"] == "C1"
    assert citations[0]["record_id"] == 7
    assert "[C1]" in append_citation_section("Answer", citations)


def test_clinical_trial_rows_receive_registry_citations():
    citations = build_citations("sql", [{
        "nct_id": "NCT01234567",
        "brief_title": "Example exact-linked study",
    }])

    assert citations[0]["source"] == "ClinicalTrials.gov"
    assert citations[0]["record_type"] == "clinical_trial"
    assert citations[0]["record_id"] == "NCT01234567"


def test_target_and_disease_rows_receive_open_targets_citations():
    citations = build_citations("sql", [
        {
            "drug_id": 42,
            "drug_name": "Examplemab",
            "chembl_id": "CHEMBL42",
            "ensembl_id": "ENSG00000146648",
            "target_symbol": "EGFR",
        },
        {
            "drug_id": 42,
            "drug_name": "Examplemab",
            "chembl_id": "CHEMBL42",
            "disease_id": "EFO_0000270",
            "disease_name": "asthma",
        },
    ])

    assert citations[0]["source"] == "Open Targets"
    assert citations[0]["record_type"] == "drug_target"
    assert citations[1]["record_type"] == "drug_indication"


def test_uniprot_rows_receive_protein_citations():
    citations = build_citations("sql", [{
        "ensembl_id": "ENSG00000142192",
        "primary_accession": "P29274",
        "gene_symbol": "ADORA2A",
        "protein_name": "Adenosine receptor A2a",
        "source": "uniprot_rest",
    }])

    assert citations == [{
        "id": "C1",
        "source": "UniProt",
        "record_type": "protein",
        "record_id": "P29274",
        "label": "Adenosine receptor A2a",
    }]


def test_europe_pmc_rows_receive_publication_citations():
    citations = build_citations("sql", [{
        "article_source": "MED",
        "external_id": "18832607",
        "title": "A2A receptor structure",
        "ensembl_id": "ENSG00000128271",
    }])

    assert citations == [{
        "id": "C1",
        "source": "Europe PMC",
        "record_type": "publication",
        "record_id": "MED:18832607",
        "label": "A2A receptor structure",
    }]
