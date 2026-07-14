"""Tests for PubChem response handling without network access."""

import io
import json
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from unified_api.services.pubchem_enrichment import (
    PubChemClient,
    enrich_pubchem_batch,
    pubchem_match_context_supported,
)


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_pubchem_client_parses_single_exact_name_result():
    payload = {"PropertyTable": {"Properties": [{
        "CID": 73078,
        "Title": "Tetrandrine",
        "InChIKey": "WVTKBKWTSCPRNU-KYJUHHDHSA-N",
        "ConnectivitySMILES": "CN1CCC",
    }]}}
    with patch(
        "unified_api.services.pubchem_enrichment.urlopen",
        return_value=Response(json.dumps(payload).encode()),
    ):
        match = PubChemClient(delay_seconds=0).lookup_name("tetrandrine")

    assert match.cid == 73078
    assert match.title == "Tetrandrine"
    assert match.inchikey == "WVTKBKWTSCPRNU-KYJUHHDHSA-N"


def test_pubchem_client_treats_404_as_not_found():
    error = HTTPError("https://example.test", 404, "not found", {}, None)
    with patch(
        "unified_api.services.pubchem_enrichment.urlopen", side_effect=error
    ):
        assert PubChemClient(delay_seconds=0).lookup_name("not-a-drug") is None


def test_pubchem_client_rejects_ambiguous_multiple_results():
    payload = {"PropertyTable": {"Properties": [{"CID": 1}, {"CID": 2}]}}
    with patch(
        "unified_api.services.pubchem_enrichment.urlopen",
        return_value=Response(json.dumps(payload).encode()),
    ):
        assert PubChemClient(delay_seconds=0).lookup_name("ambiguous") is None


def test_pubchem_client_retries_throttled_request():
    payload = {"PropertyTable": {"Properties": [{
        "CID": 2244,
        "Title": "Aspirin",
        "InChIKey": "BSYNRYMUTXBXSQ-UHFFFAOYSA-N",
        "ConnectivitySMILES": "CC(=O)OC1=CC=CC=C1C(=O)O",
    }]}}
    error = HTTPError(
        "https://example.test",
        503,
        "throttled",
        {"Retry-After": "0"},
        None,
    )
    with (
        patch(
            "unified_api.services.pubchem_enrichment.urlopen",
            side_effect=[error, Response(json.dumps(payload).encode())],
        ),
        patch("unified_api.services.pubchem_enrichment.time.sleep") as sleep,
    ):
        match = PubChemClient(delay_seconds=0).lookup_name("aspirin")

    assert match.cid == 2244
    sleep.assert_called_once_with(0.0)


def test_macro_biologic_development_code_requires_corroboration():
    supported, reason = pubchem_match_context_supported(
        query_name="CS-2012",
        pubchem_title="Ro 25-6981 maleate",
        alias_type="display_name",
        technologies=["Antibody", "Multispecific", "T-cell engager"],
        corroborating_aliases=[],
    )

    assert supported is False
    assert reason == "uncorroborated_macro_biologic_development_code"


def test_macro_biologic_code_accepts_source_corroborated_pubchem_title():
    supported, reason = pubchem_match_context_supported(
        query_name="MK-3475",
        pubchem_title="Pembrolizumab",
        alias_type="development_code",
        technologies=["Monoclonal antibody"],
        corroborating_aliases=["Pembrolizumab"],
    )

    assert supported is True
    assert reason == "pubchem_title_corroborated_by_source_alias"


def test_non_code_or_non_macro_context_preserves_exact_name_lookup():
    ordinary = pubchem_match_context_supported(
        query_name="Aspirin",
        pubchem_title="Aspirin",
        technologies=["Small molecule"],
    )
    peptide = pubchem_match_context_supported(
        query_name="ABC-123",
        pubchem_title="A peptide title",
        technologies=["Peptide", "Biological"],
    )

    assert ordinary[0] is True
    assert peptide[0] is True


def _lock_connection(*, acquired: bool) -> Mock:
    connection = Mock()
    connection.execute.return_value.scalar.return_value = acquired
    return connection


def test_pubchem_batch_skips_before_querying_when_another_batch_holds_lock():
    connection = _lock_connection(acquired=False)
    engine = Mock()
    engine.connect.return_value = connection
    with (
        patch(
            "unified_api.services.pubchem_enrichment.ensure_pubchem_schema"
        ),
        patch(
            "unified_api.services.pubchem_enrichment.get_cortellis_engine",
            return_value=engine,
        ),
        patch("unified_api.services.pubchem_enrichment._candidates") as candidates,
    ):
        result = enrich_pubchem_batch()

    assert result == {
        "status": "busy",
        "reason": "PubChem enrichment already running",
        "processed": 0,
        "matched": 0,
        "not_found": 0,
        "context_conflicts": 0,
        "failed": 0,
    }
    candidates.assert_not_called()
    connection.close.assert_called_once_with()


def test_pubchem_batch_releases_lock_after_empty_batch():
    connection = _lock_connection(acquired=True)
    engine = Mock()
    engine.connect.return_value = connection
    with (
        patch(
            "unified_api.services.pubchem_enrichment.ensure_pubchem_schema"
        ),
        patch(
            "unified_api.services.pubchem_enrichment.get_cortellis_engine",
            return_value=engine,
        ),
        patch(
            "unified_api.services.pubchem_enrichment._candidates",
            return_value=[],
        ),
    ):
        result = enrich_pubchem_batch()

    assert result == {
        "status": "completed",
        "processed": 0,
        "matched": 0,
        "not_found": 0,
        "context_conflicts": 0,
        "failed": 0,
    }
    assert connection.execute.call_count == 2
    connection.close.assert_called_once_with()
