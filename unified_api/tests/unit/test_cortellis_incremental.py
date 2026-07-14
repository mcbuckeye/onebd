"""Regression tests for date-safe Cortellis incremental queries."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import httpx
import pytest

from src.api_client import CortellisAPIError, CortellisClient, DealRecord, SearchResult
from src.config import CortellisConfig
from src.sync import (
    assess_catalog_coverage,
    assess_zero_result_window,
    retrieval_covers_advertised_catalog,
    validate_catalog_membership_by_retrieval,
)


def test_updated_deals_query_replays_overlap_window():
    query = CortellisClient.build_updated_deals_query(
        datetime(2026, 7, 11, 6, 30, tzinfo=timezone.utc),
        overlap_days=2,
    )

    assert query == "dealDateUpdate:RANGE(>2026-07-09)"


def test_updated_deals_query_combines_additional_filter():
    query = CortellisClient.build_updated_deals_query(
        datetime(2026, 7, 11, 23, 59),
        query="dealStatus:Active",
        overlap_days=1,
    )

    assert query == (
        "(dealStatus:Active) AND (dealDateUpdate:RANGE(>2026-07-10))"
    )


def test_midnight_watermark_replays_the_complete_prior_day():
    query = CortellisClient.build_updated_deals_query(
        datetime(2026, 7, 11, 0, 0, 0, tzinfo=timezone.utc),
        overlap_days=1,
    )

    assert query == "dealDateUpdate:RANGE(>2026-07-10)"


def test_updated_deal_count_uses_lightweight_search():
    client = CortellisClient(CortellisConfig("user", "password", "https://example.test"))
    client.search_deals = Mock(return_value=SearchResult(112, 0, 1, [123]))

    count = client.count_updated_deals_since(
        datetime(2026, 7, 11, 6, 30),
        overlap_days=2,
    )

    assert count == 112
    client.search_deals.assert_called_once_with(
        query="dealDateUpdate:RANGE(>2026-07-09)",
        offset=0,
        hits=1,
    )


def test_recent_zero_result_is_valid_when_source_catalog_is_nonempty():
    valid, reason = assess_zero_result_window(
        datetime(2026, 7, 11, 6, 30),
        datetime(2026, 7, 11, 7, 0),
        source_total=146_916,
    )

    assert valid is True
    assert reason == "validated zero-result window"


def test_catalog_coverage_finds_historical_omissions_without_deleting_extras():
    coverage = assess_catalog_coverage(
        remote_ids=[1, 2, 3, 4],
        local_ids=[1, 3, 9],
        expected_remote_total=4,
    )

    assert coverage["scan_complete"] is True
    assert coverage["missing_ids"] == [2, 4]
    assert coverage["extra_ids"] == [9]
    assert coverage["local_total"] == 3


def test_catalog_coverage_rejects_an_incomplete_api_scan():
    coverage = assess_catalog_coverage(
        remote_ids=[1, 2, 2],
        local_ids=[1, 2],
        expected_remote_total=3,
    )

    assert coverage["scan_complete"] is False


def _deal_record(deal_id: int) -> DealRecord:
    return DealRecord(id=deal_id, raw_xml=f'<Deal id="{deal_id}"/>', parsed_data={})


def test_retrieval_membership_audit_proves_every_local_id():
    client = Mock()
    client.get_deal_records.side_effect = lambda ids: [
        _deal_record(deal_id) for deal_id in ids
    ]

    result = validate_catalog_membership_by_retrieval(
        client,
        list(range(1, 66)),
        batch_size=30,
        workers=1,
    )

    assert result == {
        "requested_total": 65,
        "returned_unique_total": 65,
        "complete": True,
        "missing_ids": [],
        "unexpected_ids": [],
        "duplicate_ids": [],
        "errors": [],
    }
    assert [call.args[0] for call in client.get_deal_records.call_args_list] == [
        list(range(1, 31)),
        list(range(31, 61)),
        list(range(61, 66)),
    ]


def test_retrieval_membership_audit_never_certifies_an_empty_catalog():
    result = validate_catalog_membership_by_retrieval(Mock(), [])

    assert result["complete"] is False
    assert result["requested_total"] == 0


def test_retrieval_membership_audit_rejects_omitted_ids():
    client = Mock()
    client.get_deal_records.return_value = [_deal_record(1), _deal_record(3)]

    result = validate_catalog_membership_by_retrieval(client, [1, 2, 3])

    assert result["complete"] is False
    assert result["missing_ids"] == [2]
    assert result["returned_unique_total"] == 2


def test_retrieval_membership_audit_rejects_duplicates_and_unexpected_ids():
    client = Mock()
    client.get_deal_records.return_value = [
        _deal_record(1),
        _deal_record(1),
        _deal_record(9),
    ]

    result = validate_catalog_membership_by_retrieval(client, [1, 2])

    assert result["complete"] is False
    assert result["missing_ids"] == [2]
    assert result["unexpected_ids"] == [9]
    assert result["duplicate_ids"] == [1]


def test_retrieval_membership_audit_preserves_batch_errors():
    client = Mock()

    def fetch(ids):
        if ids[0] == 31:
            raise CortellisAPIError("temporary failure")
        return [_deal_record(deal_id) for deal_id in ids]

    client.get_deal_records.side_effect = fetch
    result = validate_catalog_membership_by_retrieval(
        client,
        list(range(1, 40)),
        batch_size=30,
        workers=1,
    )

    assert result["complete"] is False
    assert result["missing_ids"] == [31]
    assert result["returned_unique_total"] == 38
    assert result["errors"] == ["deal 31: temporary failure"]


def test_retrieval_coverage_allows_retained_inactive_local_ids():
    membership = {
        "returned_unique_total": 3,
        "errors": [],
        "unexpected_ids": [],
        "duplicate_ids": [],
    }

    assert retrieval_covers_advertised_catalog(membership, 3, 3) is True


def test_retrieval_coverage_rejects_count_drift_or_request_errors():
    membership = {
        "returned_unique_total": 3,
        "errors": [],
        "unexpected_ids": [],
        "duplicate_ids": [],
    }

    assert retrieval_covers_advertised_catalog(membership, 3, 4) is False
    membership["errors"] = ["deal 9: temporary failure"]
    assert retrieval_covers_advertised_catalog(membership, 3, 3) is False


def test_parallel_catalog_scan_fetches_every_page_once():
    client = CortellisClient(CortellisConfig("user", "password", "https://example.test"))
    initial = SearchResult(250, 0, 100, list(range(100)))

    def page(*, query, offset, hits, sort_by):
        assert query == "*"
        assert hits == 100
        assert sort_by == "dealId"
        end = min(offset + hits, 250)
        return SearchResult(250, offset, end - offset, list(range(offset, end)))

    client.search_deals = Mock(side_effect=page)

    deal_ids = list(client.get_all_deal_ids(
        "*",
        workers=4,
        initial_result=initial,
        sort_by="dealId",
    ))

    assert sorted(deal_ids) == list(range(250))
    assert {call.kwargs["offset"] for call in client.search_deals.call_args_list} == {
        100,
        200,
    }
    assert all(
        call.kwargs["sort_by"] == "dealId"
        for call in client.search_deals.call_args_list
    )


@pytest.mark.parametrize(
    ("watermark", "now", "source_total", "reason"),
    [
        (
            datetime(2026, 7, 12),
            datetime(2026, 7, 11),
            146_916,
            "watermark is in the future",
        ),
        (
            datetime(2026, 7, 1),
            datetime(2026, 7, 11),
            146_916,
            "zero results with a stale watermark",
        ),
        (
            datetime(2026, 7, 11),
            datetime(2026, 7, 11),
            0,
            "source catalog probe returned zero records",
        ),
    ],
)
def test_suspicious_zero_results_are_rejected(
    watermark,
    now,
    source_total,
    reason,
):
    assert assess_zero_result_window(
        watermark,
        now,
        source_total,
    ) == (False, reason)


def test_zero_result_assessment_handles_timezone_boundaries():
    valid, _ = assess_zero_result_window(
        datetime(2026, 7, 11, 23, 30, tzinfo=timezone(timedelta(hours=-4))),
        datetime(2026, 7, 12, 3, 31, tzinfo=timezone.utc),
        source_total=146_916,
    )

    assert valid is True


def test_api_request_retries_transient_network_errors():
    client = CortellisClient(CortellisConfig("user", "password", "https://example.test"))
    request = httpx.Request("GET", "https://example.test/deals")
    response = httpx.Response(200, request=request, text="ok")
    transport = Mock()
    transport.request.side_effect = [
        httpx.RequestError("temporary", request=request),
        response,
    ]
    client._client = transport

    with patch("src.api_client.time.sleep") as sleep:
        assert client._request("GET", str(request.url)) is response

    sleep.assert_called_once_with(5)


def test_api_request_stops_after_retry_budget():
    client = CortellisClient(CortellisConfig("user", "password", "https://example.test"))
    request = httpx.Request("GET", "https://example.test/deals")
    transport = Mock()
    transport.request.side_effect = httpx.RequestError("down", request=request)
    client._client = transport

    with patch("src.api_client.time.sleep"), pytest.raises(
        CortellisAPIError,
        match="Request failed",
    ):
        client._request("GET", str(request.url))

    assert transport.request.call_count == 3


def test_contract_lookup_accepts_successful_empty_response_as_no_contracts():
    client = CortellisClient(CortellisConfig("user", "password", "https://example.test"))
    request = httpx.Request("GET", "https://example.test/contracts")
    client._request = Mock(return_value=httpx.Response(
        200,
        request=request,
        text='<?xml version="1.0"?><dealContractsOutput/>',
    ))

    assert client.get_deal_contracts(123) == []


def test_deal_source_lookup_preserves_raw_response_and_citations():
    client = CortellisClient(CortellisConfig("user", "password", "https://example.test"))
    request = httpx.Request("GET", "https://example.test/sources")
    raw_xml = (
        '<?xml version="1.0"?><dealSourcesOutput><Sources>'
        '<Source id="1234" type="News"/>'
        '<Source id="5678" type="Press Release"/>'
        '</Sources></dealSourcesOutput>'
    )
    client._request = Mock(return_value=httpx.Response(
        200,
        request=request,
        text=raw_xml,
    ))

    result = client.get_deal_sources(99)

    assert result.deal_id == 99
    assert result.raw_response == raw_xml
    assert [(source.source_id, source.source_type) for source in result.sources] == [
        ("1234", "News"),
        ("5678", "Press Release"),
    ]
    assert client._request.call_args.kwargs["params"] == {"fmt": "xml"}


@pytest.mark.parametrize("status_code", [404, 503])
def test_contract_lookup_propagates_http_errors_for_retry(status_code):
    client = CortellisClient(CortellisConfig("user", "password", "https://example.test"))
    client._request = Mock(side_effect=CortellisAPIError(
        "request error",
        status_code=status_code,
    ))

    with pytest.raises(CortellisAPIError, match="request error"):
        client.get_deal_contracts(123)
