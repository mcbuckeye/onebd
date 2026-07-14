"""Tests for exact-LEI Wikidata domain enrichment."""

import pytest

from unified_api.services.wikidata_company_domain import (
    _upsert_domains,
    parse_wikidata_domains,
)


def _payload(*bindings):
    return {"results": {"bindings": list(bindings)}}


def _binding(item="Q25463170", website=None):
    result = {
        "item": {
            "type": "uri",
            "value": f"http://www.wikidata.org/entity/{item}",
        }
    }
    if website:
        result["website"] = {"type": "uri", "value": website}
    return result


def test_parse_domains_accepts_one_item_and_deduplicates_hostname():
    status, item_id, domains = parse_wikidata_domains(_payload(
        _binding(website="https://www.roche.com/"),
        _binding(website="https://roche.com/investors"),
    ))

    assert status == "matched"
    assert item_id == "Q25463170"
    assert domains == [{
        "identifier_type": "domain",
        "identifier_value": "https://roche.com/investors",
        "normalized_value": "roche.com",
    }]


def test_parse_domains_distinguishes_no_item_no_domain_and_ambiguity():
    assert parse_wikidata_domains(_payload()) == ("no_match", None, [])
    assert parse_wikidata_domains(_payload(_binding())) == (
        "no_domain",
        "Q25463170",
        [],
    )
    assert parse_wikidata_domains(_payload(
        _binding("Q1", "https://one.example"),
        _binding("Q2", "https://two.example"),
    ))[0] == "ambiguous"


@pytest.mark.parametrize(
    "binding",
    [
        {
            "item": {
                "type": "uri",
                "value": "https://example.com/entity/Q1",
            }
        },
        _binding(website="javascript:alert(1)"),
    ],
)
def test_parse_domains_rejects_unexpected_uris(binding):
    with pytest.raises(ValueError, match="Unexpected Wikidata"):
        parse_wikidata_domains(_payload(binding))


class _Result:
    def __init__(self, *, rows=None, first=None):
        self.rows = rows or []
        self.first_value = first

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.first_value


class _DomainSession:
    def __init__(self, conflicts=None):
        self.conflicts = conflicts or []
        self.inserted = []

    def execute(self, statement, params=None):
        sql = str(statement)
        if "SELECT normalized_value, company_id" in sql:
            return _Result(rows=self.conflicts)
        if "INSERT INTO company_identifiers" in sql:
            self.inserted.append(params)
            return _Result(first=(1,))
        raise AssertionError(f"Unexpected SQL: {sql}")


def test_shared_domain_is_quarantined_before_any_insert():
    session = _DomainSession(conflicts=[{
        "normalized_value": "shared.example",
        "company_id": 99,
    }])

    result = _upsert_domains(
        session,
        {"company_id": 10, "lei": "549300U41AUUVOAAOB37"},
        [{
            "identifier_type": "domain",
            "identifier_value": "https://shared.example",
            "normalized_value": "shared.example",
        }],
        item_id="Q1",
        response_sha="a" * 64,
        request_url="https://query.wikidata.org/sparql",
    )

    assert result == ("shared_domain", 0)
    assert session.inserted == []
