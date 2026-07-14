"""Tests for exact, resumable Europe PMC target-literature evidence."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from unified_api.services import europe_pmc_enrichment


ACCESSION = "P29274"
ENSEMBL_ID = "ENSG00000128271"


def _query():
    return europe_pmc_enrichment.exact_target_query(
        accession=ACCESSION,
        ensembl_id=ENSEMBL_ID,
    )


def _result():
    return {
        "id": "18832607",
        "source": "MED",
        "pmid": "18832607",
        "pmcid": "PMC2586971",
        "doi": "10.1126/science.1164772",
        "title": "A&lt;sub&gt;2A&lt;/sub&gt; receptor structure",
        "abstractText": "An &lt;i&gt;exact&lt;/i&gt; target abstract.",
        "authorString": "Jaakola VP, et al.",
        "journalInfo": {"journal": {"title": "Science"}},
        "pubYear": "2008",
        "firstPublicationDate": "2008-10-02",
        "pubTypeList": {"pubType": ["research-article"]},
        "meshHeadingList": {"meshHeading": [{"descriptorName": "Humans"}]},
        "chemicalList": {"chemical": [{"name": "ZM 241385"}]},
        "citedByCount": 1375,
        "isOpenAccess": "N",
        "inEPMC": "Y",
    }


def _payload(*, query=None):
    return {
        "version": "6.9",
        "hitCount": 115,
        "nextCursorMark": "next-page",
        "request": {"queryString": query or _query()},
        "resultList": {"result": [_result()]},
    }


def test_exact_target_query_uses_only_validated_structured_identifiers():
    query = _query()

    assert "ACCESSION_TYPE:uniprot" in query
    assert "ACCESSION_ID:P29274" in query
    assert "UNIPROT_PUBS:P29274" in query
    assert "ACCESSION_TYPE:ensembl" in query
    assert "ACCESSION_ID:ENSG00000128271" in query

    with pytest.raises(ValueError, match="Invalid UniProt"):
        europe_pmc_enrichment.exact_target_query(
            accession="P29274 OR OPEN_ACCESS:Y",
            ensembl_id=ENSEMBL_ID,
        )
    with pytest.raises(ValueError, match="Invalid Ensembl"):
        europe_pmc_enrichment.exact_target_query(
            accession=ACCESSION,
            ensembl_id="EGFR",
        )


def test_client_uses_core_cursor_pagination_and_exact_query():
    client = europe_pmc_enrichment.EuropePmcClient(
        base_url="https://example.test/rest"
    )
    calls = []

    class Http:
        def get_json(self, path, params):
            calls.append((path, params))
            return SimpleNamespace(payload=_payload())

    client._http = Http()
    payload = client.target_publications(
        accession=ACCESSION,
        ensembl_id=ENSEMBL_ID,
        cursor_mark="cursor-1",
        page_size=100,
    )

    assert payload["version"] == "6.9"
    assert calls == [("/search", {
        "query": _query(),
        "format": "json",
        "resultType": "core",
        "pageSize": 100,
        "cursorMark": "cursor-1",
        "sort": "CITED desc",
    })]


def test_client_rejects_query_drift_and_invalid_page_size():
    client = europe_pmc_enrichment.EuropePmcClient(
        base_url="https://example.test/rest"
    )
    client._http = SimpleNamespace(get_json=lambda *_args, **_kwargs:
        SimpleNamespace(payload=_payload(query="free text")))

    with pytest.raises(ValueError, match="exact target query"):
        client.target_publications(
            accession=ACCESSION,
            ensembl_id=ENSEMBL_ID,
        )
    with pytest.raises(ValueError, match="page size"):
        client.target_publications(
            accession=ACCESSION,
            ensembl_id=ENSEMBL_ID,
            page_size=1001,
        )


def test_publication_normalization_keeps_source_ids_and_raw_metadata():
    values = europe_pmc_enrichment._publication_values(_result(), "6.9")

    assert values["article_source"] == "MED"
    assert values["external_id"] == "18832607"
    assert values["title"] == "A2A receptor structure"
    assert values["abstract_text"] == "An exact target abstract."
    assert values["journal_title"] == "Science"
    assert values["first_publication_date"].isoformat() == "2008-10-02"
    assert values["is_open_access"] is False
    assert values["in_europe_pmc"] is True
    assert values["source_url"].endswith("/article/MED/18832607")
    assert len(values["raw_sha"]) == 64


def test_page_retention_advances_durable_cursor(monkeypatch):
    calls = []

    class Session:
        def execute(self, statement, params=None):
            calls.append((str(statement), params or {}))

    @contextmanager
    def fake_session():
        yield Session()

    monkeypatch.setattr(
        europe_pmc_enrichment, "get_cortellis_session", fake_session
    )
    monkeypatch.setattr(
        europe_pmc_enrichment,
        "_upsert_publication",
        lambda _session, result, source_version: {
            "article_source": result["source"],
            "external_id": result["id"],
        },
    )
    candidate = {
        "ensembl_id": ENSEMBL_ID,
        "accession": ACCESSION,
        "cursor_mark": "*",
        "processed_results": 0,
        "pages_fetched": 0,
    }

    result = europe_pmc_enrichment._retain_page(
        candidate=candidate,
        payload=_payload(),
        source_query=_query(),
    )

    assert result["target_status"] == "in_progress"
    assert result["target_processed_results"] == 1
    state_params = calls[-1][1]
    assert state_params["status"] == "in_progress"
    assert state_params["next_cursor"] == "next-page"
    assert state_params["processed"] == 1
    assert state_params["pages_fetched"] == 1


def test_global_lock_skips_overlapping_europe_pmc_enrichment(monkeypatch):
    connection = Mock()
    connection.execute.return_value.scalar.return_value = False
    engine = Mock()
    engine.connect.return_value = connection
    monkeypatch.setattr(
        europe_pmc_enrichment, "ensure_europe_pmc_schema", lambda: None
    )
    monkeypatch.setattr(
        europe_pmc_enrichment, "get_cortellis_engine", lambda: engine
    )

    result = europe_pmc_enrichment.enrich_europe_pmc_target_literature()

    assert result == {
        "status": "skipped",
        "reason": "Europe PMC enrichment already running",
    }
    connection.close.assert_called_once_with()
