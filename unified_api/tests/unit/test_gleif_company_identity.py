"""Tests for conservative GLEIF identity and ownership decisions."""

import pytest

from unified_api.services.gleif_company_identity import (
    GleifClient,
    _relationship_links,
    _upsert_ownership,
    gleif_record_names,
    normalize_lei,
    select_unique_gleif_match,
    strict_legal_name,
)


ROCHE_LEI = "549300U41AUUVOAAOB37"
PARENT_LEI = "765LHXWGK1KXCLTFYQ30"


def _record(
    lei: str,
    legal_name: str,
    *,
    other_names=None,
    registration_status="ISSUED",
    entity_status="ACTIVE",
):
    return {
        "id": lei,
        "attributes": {
            "lei": lei,
            "entity": {
                "legalName": {"name": legal_name},
                "otherNames": [
                    {"name": name, "type": "ALTERNATIVE_LANGUAGE_LEGAL_NAME"}
                    for name in (other_names or [])
                ],
                "transliteratedOtherNames": [],
                "status": entity_status,
            },
            "registration": {
                "status": registration_status,
                "corroborationLevel": "FULLY_CORROBORATED",
            },
        },
    }


def test_lei_validation_and_strict_name_normalization():
    assert normalize_lei("5493-00U4-1AUU-VOAA-OB37") == ROCHE_LEI
    assert strict_legal_name("Roche Holding AG") == "roche holding ag"
    assert strict_legal_name("Roche Holding Ltd") == "roche holding ltd"
    with pytest.raises(ValueError, match="Invalid LEI"):
        normalize_lei("not-an-lei")


def test_unique_match_accepts_exact_alternate_legal_name():
    record = _record(
        ROCHE_LEI,
        "Roche Holding AG",
        other_names=["Roche Holding Ltd", "Roche Holding SA"],
    )

    status, selected, matched_name = select_unique_gleif_match(
        [record],
        ["Roche Holding Ltd"],
    )

    assert status == "matched"
    assert selected == record
    assert matched_name == "Roche Holding Ltd"
    assert gleif_record_names(record) == [
        "Roche Holding AG",
        "Roche Holding Ltd",
        "Roche Holding SA",
    ]


def test_unique_match_rejects_ambiguity_and_inactive_records():
    first = _record(ROCHE_LEI, "Example Pharma Inc")
    second = _record(PARENT_LEI, "Example Pharma Inc")
    assert select_unique_gleif_match(
        [first, second], ["Example Pharma Inc"]
    )[0] == "ambiguous"

    inactive = _record(
        ROCHE_LEI,
        "Example Pharma Inc",
        entity_status="INACTIVE",
        registration_status="RETIRED",
    )
    assert select_unique_gleif_match(
        [inactive], ["Example Pharma Inc"]
    )[0] == "inactive"


def test_unique_match_prefers_one_issued_record_over_lapsed_duplicate():
    issued = _record(ROCHE_LEI, "Example Pharma Inc")
    lapsed = _record(
        PARENT_LEI,
        "Example Pharma Inc",
        registration_status="LAPSED",
    )

    status, selected, _ = select_unique_gleif_match(
        [lapsed, issued], ["Example Pharma Inc"]
    )

    assert status == "matched"
    assert selected == issued


def test_relationship_links_require_both_official_endpoints():
    record = {
        "relationships": {
            "direct-parent": {
                "links": {
                    "lei-record": "https://api.gleif.org/api/v1/parent",
                    "relationship-record": "https://api.gleif.org/api/v1/relation",
                }
            }
        }
    }
    assert _relationship_links(record) == (
        "https://api.gleif.org/api/v1/parent",
        "https://api.gleif.org/api/v1/relation",
    )
    assert _relationship_links({"relationships": {}}) is None


def test_related_endpoint_rejects_non_gleif_hosts():
    client = GleifClient()
    with pytest.raises(ValueError, match="unexpected GLEIF relationship URL"):
        client.related("https://example.com/api/v1/parent")


class _Result:
    def __init__(self, value=None):
        self.value = value

    def scalar(self):
        return self.value

    def first(self):
        return self.value


class _OwnershipSession:
    def __init__(self):
        self.insert_params = None

    def execute(self, statement, params=None):
        sql = str(statement)
        if "SELECT company_id FROM company_identifiers" in sql:
            return _Result(20)
        if "INSERT INTO company_identity_relationships" in sql:
            self.insert_params = params
            return _Result((99,))
        raise AssertionError(f"Unexpected SQL: {sql}")


def test_fully_corroborated_active_relationship_is_verified():
    session = _OwnershipSession()
    parent = _record(PARENT_LEI, "Parent Pharma Inc")
    relationship = {
        "id": "relationship-1",
        "attributes": {
            "validFrom": "2024-01-01T00:00:00Z",
            "relationship": {
                "startNode": {"id": ROCHE_LEI, "type": "LEI"},
                "endNode": {"id": PARENT_LEI, "type": "LEI"},
                "type": "IS_DIRECTLY_CONSOLIDATED_BY",
                "status": "ACTIVE",
                "periods": [],
            },
            "registration": {
                "status": "PUBLISHED",
                "corroborationLevel": "FULLY_CORROBORATED",
                "corroborationDocuments": "ACCOUNTS_FILING",
            },
        },
    }

    result = _upsert_ownership(
        session,
        {"company_id": 10, "company_name": "Child Pharma", "lei": ROCHE_LEI},
        parent,
        relationship,
        request_url="https://api.gleif.org/api/v1/relation",
        response_sha="a" * 64,
    )

    assert result == ("matched", 1, PARENT_LEI, "Parent Pharma Inc")
    assert session.insert_params["parent_company_id"] == 20
    assert session.insert_params["child_company_id"] == 10
    assert session.insert_params["review_status"] == "verified"
    assert session.insert_params["confidence"] == 1.0
