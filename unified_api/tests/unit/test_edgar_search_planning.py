"""EDGAR endpoint query-plan selection tests."""

from contextlib import contextmanager

import pytest

from unified_api.routers.edgar import search_edgar_filings
from unified_api.services import database


class _Result:
    def __init__(self, rows=(), scalar=None):
        self._rows = rows
        self._scalar = scalar

    def __iter__(self):
        return iter(self._rows)

    def scalar_one(self):
        return self._scalar


class _Session:
    def __init__(self, eligible_documents=0):
        self.eligible_documents = eligible_documents
        self.calls = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if "SELECT COUNT(*)" in sql:
            return _Result(scalar=self.eligible_documents)
        return _Result()


def _install_session(monkeypatch, session):
    @contextmanager
    def _session_context():
        yield session

    monkeypatch.setattr(database, "get_edgar_source_session", _session_context)


@pytest.mark.asyncio
async def test_common_form_search_uses_bounded_recent_sample(monkeypatch):
    session = _Session(eligible_documents=48_648)
    _install_session(monkeypatch, session)

    results = await search_edgar_filings(
        query="agreement",
        mode="fulltext",
        doc_type="8-K",
        company=None,
        limit=5,
    )

    assert results == []
    assert len(session.calls) == 2
    sql, params = session.calls[-1]
    assert "text_candidates AS MATERIALIZED" in sql
    assert "ORDER BY c.id DESC" in sql
    assert params["sample_limit"] == 1000


@pytest.mark.asyncio
async def test_rare_form_search_keeps_exact_fulltext_plan(monkeypatch):
    session = _Session(eligible_documents=750)
    _install_session(monkeypatch, session)

    await search_edgar_filings(
        query="agreement",
        mode="fulltext",
        doc_type="S-1/A",
        company=None,
        limit=5,
    )

    sql, params = session.calls[-1]
    assert "text_candidates AS MATERIALIZED" not in sql
    assert "to_tsvector('english', c.text) @@" in sql
    assert "sample_limit" not in params


@pytest.mark.asyncio
async def test_company_search_never_uses_global_sample(monkeypatch):
    session = _Session()
    _install_session(monkeypatch, session)

    await search_edgar_filings(
        query="agreement",
        mode="fulltext",
        doc_type="8-K",
        company="Example Bio",
        limit=5,
    )

    assert len(session.calls) == 1
    sql, params = session.calls[0]
    assert "text_candidates AS MATERIALIZED" not in sql
    assert "eligible_documents AS MATERIALIZED" in sql
    assert "JOIN chunks c ON c.document_id = eligible.id" in sql
    assert "e.name ILIKE :company" in sql
    assert params["company"] == "%Example Bio%"
