"""Validation, SQL binding, pagination, and evidence tests for advanced search."""

from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from unified_api.services.advanced_search import (
    AdvancedSearchRequest,
    CompanyCriterion,
    DateRange,
    MoneyRange,
    search_assets,
    search_deals,
)


class _MappingsResult:
    def __init__(self, rows=None, scalar_value=None):
        self.rows = rows or []
        self.scalar_value = scalar_value

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def scalar(self):
        return self.scalar_value


class _RecordingSession:
    def __init__(self, rows, total=0):
        self.rows = rows
        self.total = total
        self.calls = []

    def execute(self, statement, params=None):
        sql = str(statement)
        if sql.startswith("SET LOCAL"):
            return _MappingsResult()
        self.calls.append((sql, dict(params)))
        if (
            "SELECT COUNT(*) FROM filtered" in sql
            or "SELECT COUNT(DISTINCT asset_id) FROM matched" in sql
        ):
            return _MappingsResult(scalar_value=self.total)
        return _MappingsResult(rows=self.rows)


def test_request_rejects_ambiguous_company_and_invalid_ranges():
    with pytest.raises(ValidationError):
        CompanyCriterion(id=10, name="Two identities")
    with pytest.raises(ValidationError):
        DateRange(field="date_start", gte=date(2025, 2, 1), lte=date(2025, 1, 1))
    with pytest.raises(ValidationError):
        MoneyRange(gte=10, currencies=[])
    with pytest.raises(ValidationError):
        MoneyRange(gte=10, currencies=[" "])
    with pytest.raises(ValidationError, match="cannot exceed 100"):
        AdvancedSearchRequest.model_validate(
            {"values": {"royalty_rate_pct": {"gte": 101}}}
        )


def test_default_search_is_lightweight_and_cortellis_only():
    request = AdvancedSearchRequest()
    session = _RecordingSession([])

    result = search_assets(session, request, allow_public_biology=True)

    sql = session.calls[0][0]
    assert request.evidence.sources == ["cortellis_deals"]
    assert request.evidence.allowed_attribution == ["deal"]
    assert result["expanded"] == []
    assert "page AS" in sql
    assert "public_drug_target_links" not in sql
    assert "alias_agg" not in sql
    assert "company_agg" not in sql


def test_asset_expansion_is_page_first_and_total_skips_hydration():
    request = AdvancedSearchRequest.model_validate(
        {
            "limit": 5,
            "include_total": True,
            "expand": [
                "aliases",
                "companies",
                "diseases",
                "evidence",
                "modalities",
                "targets",
                "values",
            ],
            "evidence": {
                "allowed_attribution": ["asset", "deal"],
                "sources": ["cortellis_deals", "public_biology"],
            },
        }
    )
    session = _RecordingSession([], total=33912)

    result = search_assets(session, request)

    page_sql, count_sql = (call[0] for call in session.calls)
    assert result["total"] == 33912
    assert "page AS" in page_sql
    assert "page_deals AS" in page_sql
    assert "JOIN page ON page.id=matched.asset_id" in page_sql
    assert "alias_agg AS" in page_sql
    assert "SELECT COUNT(DISTINCT asset_id) FROM matched" in count_sql
    assert "alias_agg" not in count_sql
    assert "page_deals" not in count_sql


def test_date_filters_preserve_timestamp_indexes_and_alias_source_boundary():
    request = AdvancedSearchRequest.model_validate(
        {
            "assets": {"names": {"any": ["DB-003"]}},
            "dates": [
                {
                    "field": "date_start",
                    "gte": "2020-01-01",
                    "lte": "2025-12-31",
                }
            ],
        }
    )
    session = _RecordingSession([])

    search_assets(session, request)

    sql = session.calls[0][0]
    assert "deal.date_start >= CAST(" in sql
    assert "deal.date_start < CAST(" in sql
    assert "deal.date_start::date" not in sql
    assert "asset_alias.source='cortellis'" in sql
    with pytest.raises(ValidationError, match="supported for targets"):
        AdvancedSearchRequest.model_validate(
            {
                "diseases": {
                    "names": {"any": ["cancer"]},
                    "action_types": {"include": ["inhibitor"]},
                }
            }
        )


def test_deal_search_binds_all_user_values_and_normalizes_money_units():
    row = {
        "id": 42,
        "date_change_last": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "companies": [],
        "assets": [],
    }
    session = _RecordingSession([row], total=1)
    request = AdvancedSearchRequest.model_validate(
        {
            "query": "oncology",
            "companies": {"any": [{"name": "Needle Bio", "match_mode": "contains"}]},
            "assets": {
                "names": {"any": ["NB-101"], "match_mode": "exact"},
                "modalities": {"any": ["Antibody"]},
            },
            "targets": {"names": {"all": ["PD-L1"]}},
            "diseases": {"names": {"any": ["Solid tumor"]}},
            "deals": {
                "types": {"include": ["License"]},
                "territories": {"any": ["US"]},
            },
            "dates": [{"field": "date_start", "gte": "2020-01-01"}],
            "values": {
                "total_projected_current_millions": {
                    "gte": 100,
                    "currencies": ["usd"],
                },
                "upfront_usd_millions": {"gte": 10},
            },
            "include_total": True,
            "expand": [
                "assets",
                "companies",
                "diseases",
                "modalities",
                "sources",
                "targets",
            ],
            "evidence": {
                "allowed_attribution": ["asset", "deal"],
                "sources": ["cortellis_deals", "public_biology"],
            },
        }
    )

    result = search_deals(session, request)

    sql, params = session.calls[0]
    assert result["total"] == 1
    assert result["items"][0]["matched_filter_categories"] == [
        "query",
        "companies",
        "assets",
        "targets",
        "diseases",
        "deals",
        "values",
        "dates",
        "evidence",
    ]
    assert "CASE UPPER(COALESCE(finance.total_projected_current_unit" in sql
    assert "deal_financial_terms term" in sql
    assert "company_aliases alias" in sql
    assert "public_drug_target_links" in sql
    assert "deal_indications" in sql
    assert "Needle Bio" not in sql
    assert "NB-101" not in sql
    assert "%oncology%" in params.values()
    assert "%Needle Bio%" in params.values()
    assert "NB-101" in params.values()
    assert ["USD"] in params.values()


def test_asset_search_cursor_is_opaque_and_query_bound():
    rows = [
        {"id": 1, "name_display": "Asset A", "deal_count": 1},
        {"id": 2, "name_display": "Asset B", "deal_count": 1},
    ]
    first_session = _RecordingSession(rows)
    first_request = AdvancedSearchRequest(limit=1)

    first = search_assets(first_session, first_request, allow_public_biology=False)

    assert first["has_more"] is True
    assert first["next_cursor"]
    assert "Asset A" not in first["next_cursor"]
    assert "public_drug_target_links" not in first_session.calls[0][0]

    second_request = first_request.model_copy(update={"cursor": first["next_cursor"]})
    second_session = _RecordingSession([])
    search_assets(second_session, second_request, allow_public_biology=False)
    assert "result.name_display >" in second_session.calls[0][0]

    changed_query = AdvancedSearchRequest(
        limit=1,
        cursor=first["next_cursor"],
        assets={"names": {"any": ["different"]}},
    )
    with pytest.raises(ValueError, match="does not match"):
        search_assets(_RecordingSession([]), changed_query)


def test_money_sort_requires_one_currency_and_matching_filter():
    missing_filter = AdvancedSearchRequest(
        sort=[{"field": "total_paid", "direction": "desc"}]
    )
    with pytest.raises(ValueError, match="exactly one currency"):
        search_deals(_RecordingSession([]), missing_filter)

    two_currencies = AdvancedSearchRequest.model_validate(
        {
            "values": {
                "total_paid_millions": {
                    "gte": 1,
                    "currencies": ["USD", "EUR"],
                }
            },
            "sort": [{"field": "total_paid", "direction": "desc"}],
        }
    )
    with pytest.raises(ValueError, match="exactly one currency"):
        search_deals(_RecordingSession([]), two_currencies)


def test_unknown_fields_are_rejected_instead_of_silently_ignored():
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        AdvancedSearchRequest.model_validate({"unknown_filter": "value"})
