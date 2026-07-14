"""Contract tests for the source-backed DD package orchestration."""

from contextlib import contextmanager

import pytest
from fastapi import HTTPException

import unified_api.routers.dd as dd


class FakeResult:
    def __init__(self, value):
        self.value = value

    def mappings(self):
        return self

    def first(self):
        return self.value[0] if isinstance(self.value, list) and self.value else self.value

    def one(self):
        return self.value

    def all(self):
        return self.value if isinstance(self.value, list) else [self.value]


class ScriptedSession:
    def __init__(self, responses, statements):
        self.responses = iter(responses)
        self.statements = statements

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params or {}))
        return FakeResult(next(self.responses))


def scripted_context(responses, statements):
    @contextmanager
    def context():
        yield ScriptedSession(responses, statements)

    return context


async def test_dd_populates_all_previously_empty_sections(monkeypatch):
    statements = []
    cortellis_responses = [
        {
            "id": 42,
            "name": "Example Bio",
            "company_type": "Biotech",
            "ticker": "EXB",
            "hq_location": "Boston",
            "cik": "0000123456",
        },
        {
            "total_deals": 10,
            "disclosed_count": 4,
            "total_value": 800.0,
            "avg_value": 200.0,
            "max_value": 500.0,
            "terminated_deals": 1,
        },
        [{"id": 7, "name": "Partner Pharma", "deal_count": 3}],
        {
            "edgar_company_id": 99,
            "cik": "0000123456",
            "match_method": "reviewed_cik",
            "match_confidence": 1.0,
            "manually_verified": True,
        },
        [{
            "contract_id": 501,
            "deal_id": 1001,
            "deal_title": "Example license",
            "contract_types": "License",
            "date_contract": "2024-01-05 00:00:00",
            "date_filing": "2024-01-10 00:00:00",
            "has_pdf": True,
            "has_text": True,
            "is_redacted": False,
            "content_id": 601,
            "word_count": 1234,
            "financial_clause_count": 1,
            "total_contracts": 8,
            "key_financial_clauses": [{
                "id": 701,
                "clause_type": "royalty_rate",
                "review_status": "accepted",
                "parser_version": 11,
            }],
        }],
        [{
            "territory_id": "US",
            "territory": "United States",
            "scope_type": "Included",
            "deal_id": 1001,
            "deal_title": "Example license",
            "deal_status": "Active",
            "date_start": "2024-01-01 00:00:00",
            "company_role": "Principal",
            "assets": ["Asset A"],
            "total_scope_records": 12,
        }],
        [{
            "id": 2002,
            "title": "Comparable license",
            "agreement_type": "Drug - License",
            "status": "Active",
            "date_start": "2024-02-01 00:00:00",
            "phase_highest_start": "Phase 2",
            "therapy_area": "Cancer",
            "total_value": 300.0,
            "currency": "USD",
            "unit": "Million",
            "disclosure_status": "Known",
            "similarity_score": 9,
            "total_comparable_candidates": 321,
            "match_reasons": [
                "dominant agreement type",
                "dominant therapy area",
                "dominant phase at signing",
            ],
            "principal": "Peer Bio",
            "partner": "Peer Pharma",
        }],
    ]
    edgar_responses = [[{
        "id": 9001,
        "accession_no": "0000123456-24-000001",
        "doc_type": "8-K",
        "title": "Current report",
        "filing_date": "2024-03-01 00:00:00+00:00",
        "published_at": "2024-03-01 12:00:00+00:00",
        "source_url": "https://www.sec.gov/Archives/example.htm",
        "parse_ok": True,
        "chunk_count": 25,
        "total_filings": 40,
    }]]
    monkeypatch.setattr(
        dd,
        "get_cortellis_session",
        scripted_context(cortellis_responses, statements),
    )
    monkeypatch.setattr(
        dd,
        "get_edgar_session",
        scripted_context(edgar_responses, statements),
    )

    package = await dd.generate_dd_package(dd.DDGenerateRequest(
        company_id=42,
        sections=[
            "sec_filings",
            "contracts",
            "territory_rights",
            "comparable_transactions",
        ],
    ))
    sections = {section["type"]: section for section in package["sections"]}

    assert sections["sec_filings"]["content"][0]["doc_type"] == "8-K"
    assert sections["sec_filings"]["coverage"]["total_filings"] == 40
    assert sections["contracts"]["content"][0]["financial_clause_count"] == 1
    assert (
        sections["contracts"]["content"][0]["key_financial_clauses"][0]
        ["review_status"]
        == "accepted"
    )
    assert sections["territory_rights"]["content"][0]["scope_type"] == "Included"
    assert "not asserted to be current ownership" in sections["territory_rights"]["methodology"]
    assert sections["comparable_transactions"]["content"][0]["similarity_score"] == 9
    assert (
        sections["comparable_transactions"]["coverage"]
        ["total_comparable_candidates"]
        == 321
    )
    assert all(section["status"] == "available" for section in sections.values())
    assert package["metadata"]["financial_disclosure_rate"] == "40.0%"
    assert "SEC EDGAR" in package["metadata"]["sources"]

    sql = "\n".join(statement for statement, _params in statements)
    assert "total_projected_current_currency='USD'" in sql
    assert "total_projected_current_disclosure_status='Known'" in sql
    assert "clause.review_status<>'rejected'" in sql
    assert "NOT EXISTS" in sql


async def test_dd_rejects_unknown_sections_before_querying():
    with pytest.raises(HTTPException) as exc:
        await dd.generate_dd_package(dd.DDGenerateRequest(
            company_id=1,
            sections=["not_a_section"],
        ))

    assert exc.value.status_code == 400
