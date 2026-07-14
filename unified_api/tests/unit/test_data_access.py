"""Small contract tests for the governed read-only data API."""

from contextlib import contextmanager

import unified_api.routers.data_access as data_access
from unified_api.routers.data_access import SOURCE_CATALOG, _page


def test_source_catalog_separates_cortellis_from_public_enrichment():
    sources = {source["id"]: source for source in SOURCE_CATALOG}

    assert sources["cortellis_deals"]["kind"] == "commercial"
    assert "separately licensed" in sources["cortellis_deals"]["not_in_scope"]
    assert sources["open_targets"]["kind"] == "open_data"
    assert sources["clinicaltrials_gov"]["id"] != "cortellis_deals"


def test_cursor_page_never_returns_more_than_requested_limit():
    result = _page([{"id": 1}, {"id": 2}, {"id": 3}], 2, "id")

    assert result == {
        "items": [{"id": 1}, {"id": 2}],
        "limit": 2,
        "has_more": True,
        "next_cursor": 2,
    }


def test_final_cursor_page_has_no_next_cursor():
    result = _page([{"nct_id": "NCT00000001"}], 2, "nct_id")

    assert result["has_more"] is False
    assert result["next_cursor"] is None


async def test_financial_terms_page_applies_filters_and_current_parser(monkeypatch):
    observed = {}

    class Result:
        def mappings(self):
            return self

        def all(self):
            return [
                {"id": 10, "deal_id": 42, "term_type": "upfront_payment"},
                {"id": 11, "deal_id": 43, "term_type": "upfront_payment"},
            ]

    class Session:
        def execute(self, statement, params):
            observed["sql"] = str(statement)
            observed["params"] = params
            return Result()

    @contextmanager
    def session():
        yield Session()

    monkeypatch.setattr(data_access, "get_cortellis_session", session)
    result = await data_access.list_financial_terms(
        after_id=9,
        limit=1,
        deal_id=42,
        term_type="upfront_payment",
        basis="projected_current",
        disclosure_status="Known",
        min_amount_usd_millions=100,
        min_rate_pct=10,
        _principal=None,
    )

    assert result["items"] == [
        {"id": 10, "deal_id": 42, "term_type": "upfront_payment"}
    ]
    assert result["next_cursor"] == 10
    assert observed["params"]["parser_version"] == data_access.FINANCE_PARSER_VERSION
    assert observed["params"]["limit"] == 2
    assert "term.deal_id = :deal_id" in observed["sql"]
    assert "term.amount_usd_millions >= :min_amount_usd_millions" in observed["sql"]
    assert "GREATEST(term.rate_min_pct, term.rate_max_pct)" in observed["sql"]
