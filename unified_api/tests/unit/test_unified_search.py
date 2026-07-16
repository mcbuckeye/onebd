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


@pytest.mark.asyncio
async def test_both_sources_balance_incomparable_native_scores(monkeypatch):
    async def fake_contract_search(**_kwargs):
        return {
            "results": [
                {
                    "chunk_id": index,
                    "deal_id": index,
                    "contract_id": index,
                    "content": f"contract {index}",
                    "score": 0.1 / index,
                }
                for index in range(1, 4)
            ],
        }

    async def fake_edgar_search(**_kwargs):
        return [
            EdgarSearchResult(
                chunk_id=100 + index,
                document_id=100 + index,
                text=f"filing {index}",
                score=10.0 / index,
                company_name="Example Inc",
            )
            for index in range(1, 4)
        ]

    monkeypatch.setattr(search, "search_contracts", fake_contract_search)
    monkeypatch.setattr(edgar, "search_edgar_filings", fake_edgar_search)

    response = await search.unified_search(
        query="agreement",
        sources="both",
        mode="fulltext",
        limit=4,
    )

    assert [item["source"] for item in response["results"]] == [
        "cortellis", "edgar", "cortellis", "edgar",
    ]
    assert response["ranking_method"] == "source_balanced_round_robin"
    assert "not cross-source comparable" in response["score_scope"]
