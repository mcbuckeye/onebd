"""Tests for PubChem response handling without network access."""

import io
import json
from unittest.mock import patch
from urllib.error import HTTPError

from unified_api.services.pubchem_enrichment import PubChemClient


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
