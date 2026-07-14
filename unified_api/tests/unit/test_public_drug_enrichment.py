"""Tests for exact ChEMBL and Open Targets public-drug adapters."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from unified_api.services import public_drug_enrichment


def _response(payload):
    return SimpleNamespace(payload=payload)


def test_chembl_client_uses_exact_inchikey_batch_and_release_status():
    client = public_drug_enrichment.ChEMBLClient(
        base_url="https://example.test/chembl"
    )
    calls = []

    class Http:
        def get_json(self, path, params=None, **kwargs):
            calls.append((path, params, kwargs))
            if path == "/status.json":
                return _response({"chembl_db_version": "ChEMBL_37"})
            return _response({
                "molecules": [{"molecule_chembl_id": "CHEMBL25"}],
                "page_meta": {"total_count": 1},
            })

    client._http = Http()

    assert client.status()["chembl_db_version"] == "ChEMBL_37"
    payload = client.molecules_by_inchikeys([
        "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
        "WVTKBKWTSCPRNU-KYJUHHDHSA-N",
    ])

    assert payload["molecules"][0]["molecule_chembl_id"] == "CHEMBL25"
    assert calls[0] == ("/status.json", None, {"use_cache": True})
    assert calls[1][0] == "/molecule.json"
    assert calls[1][1]["molecule_structures__standard_inchi_key__in"] == (
        "BSYNRYMUTXBXSQ-UHFFFAOYSA-N,WVTKBKWTSCPRNU-KYJUHHDHSA-N"
    )
    assert calls[1][1]["limit"] == 100


def test_chembl_client_refuses_silently_truncated_exact_results():
    client = public_drug_enrichment.ChEMBLClient(
        base_url="https://example.test/chembl"
    )
    client._http = SimpleNamespace(get_json=lambda *_args, **_kwargs: _response({
        "molecules": [{"molecule_chembl_id": "CHEMBL25"}],
        "page_meta": {"total_count": 2},
    }))

    with pytest.raises(ValueError, match="exceeded"):
        client.molecules_by_inchikeys(["BSYNRYMUTXBXSQ-UHFFFAOYSA-N"])


def test_chembl_client_rejects_noncanonical_inchikeys():
    client = public_drug_enrichment.ChEMBLClient(
        base_url="https://example.test/chembl"
    )
    with pytest.raises(ValueError, match="Invalid InChIKey"):
        client.molecules_by_inchikeys(["aspirin,other-filter"])


def test_open_targets_client_batches_exact_ids_and_current_stage_schema():
    client = public_drug_enrichment.OpenTargetsClient(
        base_url="https://example.test/api/v4"
    )
    payloads = []

    class Http:
        def post_json(self, path, payload, **kwargs):
            payloads.append((path, payload, kwargs))
            query = payload["query"]
            if "d0:" not in query:
                return _response({"data": {"meta": {
                    "dataVersion": {"year": "26", "month": "06", "iteration": None},
                    "apiVersion": {"x": "26", "y": "6", "z": "3"},
                }}})
            return _response({"data": {
                "d0": {"id": "CHEMBL25", "maximumClinicalStage": "APPROVAL"},
                "d1": None,
                "meta": {
                    "dataVersion": {"year": "26", "month": "06", "iteration": None},
                    "apiVersion": {"x": "26", "y": "6", "z": "3"},
                },
            }})

    client._http = Http()

    assert public_drug_enrichment._open_targets_version(client.metadata()) == "26.06"
    profiles, metadata = client.drugs(["CHEMBL25", "CHEMBL123"])

    assert profiles["CHEMBL25"]["maximumClinicalStage"] == "APPROVAL"
    assert profiles["CHEMBL123"] is None
    assert public_drug_enrichment._open_targets_version(metadata) == "26.06"
    query = payloads[1][1]["query"]
    assert 'd0: drug(chemblId: "CHEMBL25")' in query
    assert 'd1: drug(chemblId: "CHEMBL123")' in query
    assert "maximumClinicalStage" in query
    assert "maxClinicalStage" in query
    assert "targets" in query
    assert "proteinIds" in query


def test_open_targets_client_surfaces_graphql_errors():
    client = public_drug_enrichment.OpenTargetsClient(
        base_url="https://example.test/api/v4"
    )
    client._http = SimpleNamespace(post_json=lambda *_args, **_kwargs: _response({
        "errors": [{"message": "schema changed"}],
    }))

    with pytest.raises(ValueError, match="schema changed"):
        client.metadata()


def test_open_targets_client_rejects_noncanonical_chembl_ids():
    client = public_drug_enrichment.OpenTargetsClient(
        base_url="https://example.test/api/v4"
    )
    with pytest.raises(ValueError, match="Invalid ChEMBL ID"):
        client.drugs(["CHEMBL25\") { malicious }"])


@pytest.mark.parametrize(
    ("function_name", "lock_reason"),
    [
        ("enrich_chembl_identifiers", "ChEMBL enrichment already running"),
        ("enrich_open_targets_profiles", "Open Targets enrichment already running"),
    ],
)
def test_global_locks_skip_overlapping_enrichment(
    monkeypatch, function_name, lock_reason
):
    connection = Mock()
    connection.execute.return_value.scalar.return_value = False
    engine = Mock()
    engine.connect.return_value = connection
    monkeypatch.setattr(
        public_drug_enrichment, "ensure_public_drug_schema", lambda: None
    )
    monkeypatch.setattr(
        public_drug_enrichment, "get_cortellis_engine", lambda: engine
    )

    result = getattr(public_drug_enrichment, function_name)()

    assert result == {"status": "skipped", "reason": lock_reason}
    connection.close.assert_called_once_with()
