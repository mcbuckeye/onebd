"""Small contract tests for the governed read-only data API."""

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
