"""Tests for exact, reviewed UniProt target enrichment."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from unified_api.services import uniprot_enrichment


def _entry(primary="P29274", *, secondary=None, entry_type=None):
    return {
        "primaryAccession": primary,
        "secondaryAccessions": secondary or [],
        "uniProtkbId": "AA2AR_HUMAN",
        "entryType": entry_type or "UniProtKB reviewed (Swiss-Prot)",
        "proteinDescription": {
            "recommendedName": {"fullName": {"value": "Adenosine receptor A2a"}}
        },
        "genes": [{
            "geneName": {"value": "ADORA2A"},
            "synonyms": [{"value": "ADORA2"}],
        }],
        "organism": {"scientificName": "Homo sapiens", "taxonId": 9606},
        "comments": [
            {"commentType": "FUNCTION", "texts": [{"value": "Adenosine receptor."}]},
            {"commentType": "DISEASE", "disease": {"diseaseId": "DI-1"}},
            {
                "commentType": "SUBCELLULAR LOCATION",
                "subcellularLocations": [{"location": {"value": "Cell membrane"}}],
            },
        ],
        "sequence": {"length": 412, "crc64": "ABCDEF1234567890"},
    }


def _response(payload, **headers):
    return SimpleNamespace(payload=payload, response_headers=headers)


def test_client_batches_exact_accessions_and_retains_release_metadata():
    client = uniprot_enrichment.UniProtClient(base_url="https://example.test")
    calls = []

    class Http:
        def get_json(self, path, params):
            calls.append((path, params))
            return _response(
                {"results": [_entry(), _entry("P30542")]},
                **{
                    "x-uniprot-release": "2026_02",
                    "x-uniprot-release-date": "10-June-2026",
                    "x-total-results": "2",
                },
            )

    client._http = Http()
    entries, metadata = client.entries(["p29274", "P30542"])

    assert set(entries) == {"P29274", "P30542"}
    assert metadata == {
        "release": "2026_02",
        "release_date": "10-June-2026",
    }
    assert calls[0][0] == "/uniprotkb/search"
    assert calls[0][1]["query"] == "(accession:P29274 OR accession:P30542)"
    assert calls[0][1]["format"] == "json"
    assert calls[0][1]["size"] == 2


def test_client_accepts_only_exact_primary_or_secondary_accession_matches():
    client = uniprot_enrichment.UniProtClient(base_url="https://example.test")
    client._http = SimpleNamespace(get_json=lambda *_args, **_kwargs: _response(
        {"results": [
            _entry("P29274", secondary=["Q00001"]),
            _entry("P30542"),
        ]},
        **{"x-total-results": "2"},
    ))

    entries, _metadata = client.entries(["Q00001", "P11111"])

    assert list(entries) == ["Q00001"]
    assert entries["Q00001"]["primaryAccession"] == "P29274"


def test_client_rejects_invalid_accessions_and_truncated_results():
    client = uniprot_enrichment.UniProtClient(base_url="https://example.test")
    with pytest.raises(ValueError, match="Invalid UniProt accession"):
        client.entries(["P29274 OR organism_id:9606"])

    client._http = SimpleNamespace(get_json=lambda *_args, **_kwargs: _response(
        {"results": [_entry()]},
        **{"x-total-results": "2"},
    ))
    with pytest.raises(ValueError, match="truncated"):
        client.entries(["P29274", "P30542"])


def test_normalized_fields_preserve_target_biology():
    entry = _entry()

    assert uniprot_enrichment._protein_name(entry) == "Adenosine receptor A2a"
    assert uniprot_enrichment._gene_details(entry) == ("ADORA2A", ["ADORA2"])
    assert uniprot_enrichment._function_text(entry) == "Adenosine receptor."
    assert len(uniprot_enrichment._comments(entry, "DISEASE")) == 1
    assert uniprot_enrichment._iso_release_date("10-June-2026") == "2026-06-10"


def test_global_lock_skips_overlapping_uniprot_enrichment(monkeypatch):
    connection = Mock()
    connection.execute.return_value.scalar.return_value = False
    engine = Mock()
    engine.connect.return_value = connection
    monkeypatch.setattr(
        uniprot_enrichment, "ensure_public_target_schema", lambda: None
    )
    monkeypatch.setattr(
        uniprot_enrichment, "get_cortellis_engine", lambda: engine
    )

    result = uniprot_enrichment.enrich_uniprot_targets()

    assert result == {
        "status": "skipped",
        "reason": "UniProt enrichment already running",
    }
    connection.close.assert_called_once_with()
