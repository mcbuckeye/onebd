"""Unified-search planning regressions."""

import pytest

from unified_api.routers import edgar, search
from unified_api.routers.edgar import EdgarSearchResult


@pytest.mark.asyncio
async def test_edgar_only_unified_search_reuses_bounded_edgar_plan(monkeypatch):
    observed = {}

    async def fake_search(**kwargs):
        observed.update(kwargs)
        return [EdgarSearchResult(
            chunk_id=1,
            document_id=2,
            text="agreement excerpt",
            score=0.5,
            company_name="Example Inc",
        )]

    monkeypatch.setattr(edgar, "search_edgar_filings", fake_search)

    response = await search.unified_search(
        query="agreement",
        sources="edgar",
        mode="fulltext",
        limit=40,
    )

    assert observed == {
        "query": "agreement",
        "mode": "fulltext",
        "doc_type": None,
        "company": None,
        "limit": 40,
    }
    assert response["total"] == 1
    assert response["results"][0]["content"] == "agreement excerpt"


@pytest.mark.asyncio
async def test_cortellis_only_unified_search_reuses_contract_plan(monkeypatch):
    observed = {}

    async def fake_search(**kwargs):
        observed.update(kwargs)
        return {
            "results": [{
                "chunk_id": 3,
                "deal_id": 4,
                "contract_id": 5,
                "content": "clean contract excerpt",
                "score": 0.75,
                "deal_title": "Example deal",
            }],
        }

    monkeypatch.setattr(search, "search_contracts", fake_search)

    response = await search.unified_search(
        query="agreement",
        sources="cortellis",
        mode="fulltext",
        limit=40,
    )

    assert observed == {
        "query": "agreement",
        "mode": "fulltext",
        "limit": 40,
    }
    assert response["total"] == 1
    assert response["results"][0]["content"] == "clean contract excerpt"
