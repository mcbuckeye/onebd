"""Regression tests for date-safe Cortellis incremental queries."""

from datetime import datetime, timezone
from unittest.mock import Mock

from src.api_client import CortellisClient, SearchResult
from src.config import CortellisConfig


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
