"""Governed cross-source request and SQL behavior."""

from datetime import date

import pytest

from unified_api.services.cross_source import (
    ClinicalTrialSearchRequest,
    EdgarContentSearchRequest,
    FederatedSearchRequest,
    LiteratureSearchRequest,
    ProteinSearchRequest,
    search_clinical_trials,
    search_edgar_content,
    search_literature,
    search_proteins,
)


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.calls = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if sql.startswith("SET LOCAL"):
            return _Result()
        return _Result(self.rows)


def _query_call(session):
    return next(call for call in session.calls if not call[0].startswith("SET LOCAL"))


def test_edgar_search_uses_indexable_fulltext_and_typed_filters():
    session = _Session([{"chunk_id": 9}])
    request = EdgarContentSearchRequest(
        query="license agreement",
        cik="1234",
        forms=["8-K"],
        date_from=date(2024, 1, 1),
        date_to=date(2024, 12, 31),
        limit=10,
    )

    result = search_edgar_content(session, request)

    sql, params = _query_call(session)
    assert "websearch_to_tsquery" in sql
    assert "LPAD(company.cik, 10, '0')=:cik" in sql
    assert "COALESCE(document.subtype, document.doc_type)=ANY(:forms)" in sql
    assert params["cik"] == "0000001234"
    assert params["limit"] == 11
    assert result["items"] == [{"chunk_id": 9}]


def test_advanced_trial_search_applies_all_entity_and_date_filters():
    session = _Session([{"nct_id": "NCT00000001"}])
    request = ClinicalTrialSearchRequest(
        query="oncology antibody",
        statuses=["recruiting"],
        phases=["phase 1"],
        conditions=["solid tumor"],
        sponsor="Example Bio",
        company_id=12,
        drug_id=34,
        indication_id=56,
        start_date_gte=date(2020, 1, 1),
        primary_completion_lte=date(2030, 1, 1),
        has_results=True,
    )

    search_clinical_trials(session, request)

    sql, params = _query_call(session)
    assert "clinical_trial_companies" in sql
    assert "clinical_trial_drugs" in sql
    assert "clinical_trial_indications" in sql
    assert "trial.phases ?| CAST(:phases AS text[])" in sql
    assert params["statuses"] == ["RECRUITING"]
    assert params["company_id"] == 12
    assert params["has_results"] is True


def test_literature_and_protein_company_filters_preserve_indirect_linkage():
    literature_session = _Session()
    protein_session = _Session()

    search_literature(
        literature_session,
        LiteratureSearchRequest(query="bispecific", company_id=1186341),
    )
    search_proteins(
        protein_session,
        ProteinSearchRequest(query="PD-L1", company_id=1186341),
    )

    literature_sql, _params = _query_call(literature_session)
    protein_sql, _params = _query_call(protein_session)
    assert "link.article_source=publication.article_source" in literature_sql
    assert "company_deal.company_id=:company_id" in literature_sql
    assert "target_link.ensembl_id=protein.ensembl_id" in protein_sql
    assert "company_deal.company_id=:company_id" in protein_sql


def test_federated_request_deduplicates_datasets_and_validates_dates():
    request = FederatedSearchRequest(
        query="antibody",
        datasets=["deals", "edgar", "deals"],
    )
    assert request.datasets == ["deals", "edgar"]

    with pytest.raises(ValueError, match="date_from"):
        FederatedSearchRequest(
            query="antibody",
            date_from=date(2025, 1, 2),
            date_to=date(2025, 1, 1),
        )


def test_source_models_reject_unbounded_broad_queries():
    with pytest.raises(ValueError, match="requires"):
        LiteratureSearchRequest()
    with pytest.raises(ValueError, match="requires"):
        ProteinSearchRequest()
