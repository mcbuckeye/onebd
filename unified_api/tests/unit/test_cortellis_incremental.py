"""Regression tests for date-safe Cortellis incremental queries."""

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import httpx
import pytest

from src.api_client import CortellisAPIError, CortellisClient, SearchResult
from src.config import CortellisConfig
from src.sync import assess_zero_result_window


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
