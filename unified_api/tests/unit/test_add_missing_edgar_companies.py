"""Regression tests for the targeted missing-company EDGAR backfill."""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from unified_api.scripts import add_missing_edgar_companies as script
from unified_api.services import database, edgar


class _Result:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class _ExistingCompanySession:
    def __init__(self):
        self.inserted_documents = []

    def execute(self, statement, params=None):
        sql = str(statement)
        if "SELECT id FROM companies" in sql:
            return _Result(SimpleNamespace(id=77))
        if "SELECT id FROM raw_documents" in sql:
            return _Result()
        if "INSERT INTO raw_documents" in sql:
            self.inserted_documents.append(params)
            return _Result()
        raise AssertionError(f"Unexpected SQL: {sql}")

    def commit(self):
        pass


@pytest.mark.asyncio
async def test_existing_company_still_fetches_and_inserts_missing_filings(monkeypatch):
    session = _ExistingCompanySession()

    @contextmanager
    def fake_session():
        yield session

    client = SimpleNamespace(get_company_filings=AsyncMock(return_value=[{
        "url": "https://www.sec.gov/Archives/roche-6k.htm",
        "form": "6-K",
        "filing_date": datetime(2026, 7, 1, tzinfo=timezone.utc),
        "accession_number": "0000889131-26-000001",
        "primary_document": "roche-6k.htm",
    }]))
    monkeypatch.setattr(database, "get_edgar_session", fake_session)
    monkeypatch.setattr(edgar, "get_edgar_client", lambda: client)
    monkeypatch.setattr(script, "MISSING_COMPANIES", [{
        "cik": "0000889131",
        "ticker": "RHHBY",
        "name": "Roche Holding Ltd",
        "country": "Switzerland",
        "sector": "Pharmaceuticals",
        "cortellis_id": 19446,
    }])

    await script.add_missing_companies()

    client.get_company_filings.assert_awaited_once()
    assert len(session.inserted_documents) == 1
    assert session.inserted_documents[0]["company_id"] == 77
    assert session.inserted_documents[0]["source_type"] == "sec_6_k"
