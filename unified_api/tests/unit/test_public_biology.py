"""API tests for queryable ChEMBL and Open Targets biology."""

from contextlib import contextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

from unified_api.routers import public_biology


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar_one(self):
        return self.value

    def mappings(self):
        return self

    def all(self):
        return self.value

    def first(self):
        return self.value


class _Session:
    def __init__(self, results):
        self.results = [_Result(result) for result in results]
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return self.results.pop(0)


def _client(monkeypatch, results):
    session = _Session(results)

    @contextmanager
    def fake_session():
        yield session

    monkeypatch.setattr(
        public_biology,
        "ensure_public_target_schema",
        lambda: None,
    )
    monkeypatch.setattr(
        public_biology,
        "ensure_europe_pmc_schema",
        lambda: None,
    )
    monkeypatch.setattr(public_biology, "get_cortellis_session", fake_session)
    app = FastAPI()
    app.include_router(public_biology.router, prefix="/api")
    return TestClient(app), session


def test_target_search_returns_source_links_and_uses_filters(monkeypatch):
    client, session = _client(monkeypatch, [
        1,
        [{
            "ensembl_id": "ENSG00000146648",
            "approved_symbol": "EGFR",
            "linked_drugs": 12,
            "source": "open_targets_graphql",
        }],
    ])

    response = client.get(
        "/api/public-biology/targets",
        params={"query": "egfr", "drug_id": 42, "limit": 25},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["targets"][0]["ensembl_id"] == "ENSG00000146648"
    assert session.calls[0][1]["query"] == "%egfr%"
    assert session.calls[0][1]["drug_id"] == 42
    assert "EXISTS" in session.calls[0][0]


def test_target_detail_returns_exact_mechanism_evidence(monkeypatch):
    client, _session = _client(monkeypatch, [
        {
            "ensembl_id": "ENSG00000146648",
            "approved_symbol": "EGFR",
            "source_version": "26.06",
        },
        [{
            "drug_id": 42,
            "chembl_id": "CHEMBL25",
            "mechanism_of_action": "Inhibitor",
            "source_references": [{"source": "FDA"}],
        }],
        [{
            "requested_accession": "P00533",
            "primary_accession": "P00533",
            "protein_name": "Epidermal growth factor receptor",
            "source_version": "2026_02",
        }],
    ])

    response = client.get("/api/public-biology/targets/ensg00000146648")

    assert response.status_code == 200
    payload = response.json()
    assert payload["target"]["approved_symbol"] == "EGFR"
    assert payload["linked_drugs"][0]["chembl_id"] == "CHEMBL25"
    assert payload["uniprot_records"][0]["primary_accession"] == "P00533"


def test_missing_public_disease_is_404(monkeypatch):
    client, _session = _client(monkeypatch, [None])

    response = client.get("/api/public-biology/diseases/EFO_404")

    assert response.status_code == 404
    assert response.json()["detail"] == "Public disease not found"


def test_target_literature_returns_exact_query_provenance(monkeypatch):
    client, session = _client(monkeypatch, [
        {
            "ensembl_id": "ENSG00000128271",
            "approved_symbol": "ADORA2A",
            "approved_name": "adenosine A2a receptor",
        },
        1,
        [{
            "article_source": "MED",
            "external_id": "18832607",
            "pmid": "18832607",
            "title": "A2A receptor structure",
            "requested_accessions": ["P29274"],
            "match_methods": ["exact_structured_identifier_query"],
            "source_queries": ["ACCESSION_ID:P29274"],
        }],
    ])

    response = client.get(
        "/api/public-biology/targets/ensg00000128271/literature",
        params={"limit": 25},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["target"]["approved_symbol"] == "ADORA2A"
    assert payload["total"] == 1
    assert payload["publications"][0]["requested_accessions"] == ["P29274"]
    assert session.calls[2][1]["limit"] == 25


def test_drug_biology_exposes_identifiers_profiles_targets_and_diseases(
    monkeypatch,
):
    client, session = _client(monkeypatch, [
        {"id": 42, "name_display": "Aspirin"},
        [{"identifier_type": "chembl_id", "identifier_value": "CHEMBL25"}],
        [{"chembl_id": "CHEMBL25", "raw_payload": {"pref_name": "ASPIRIN"}}],
        [{"chembl_id": "CHEMBL25", "raw_payload": {"name": "ASPIRIN"}}],
        [{"ensembl_id": "ENSG00000146648", "approved_symbol": "EGFR"}],
        [{"disease_id": "EFO_0000270", "name": "asthma"}],
    ])

    response = client.get(
        "/api/drugs/42/public-biology",
        params={"include_raw": "true"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["drug"]["name_display"] == "Aspirin"
    assert payload["identifiers"][0]["identifier_value"] == "CHEMBL25"
    assert payload["chembl_records"][0]["raw_payload"]["pref_name"] == "ASPIRIN"
    assert payload["profiles"][0]["raw_payload"]["name"] == "ASPIRIN"
    assert payload["targets"][0]["approved_symbol"] == "EGFR"
    assert payload["diseases"][0]["disease_id"] == "EFO_0000270"
    assert "record.raw_payload" in session.calls[2][0]
    assert "profile.raw_payload" in session.calls[3][0]
