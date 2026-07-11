"""Tests for incremental SEC EDGAR discovery and ingestion."""

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from unified_api.services.edgar import EDGARClient, is_priority_form, parse_master_index
from unified_api.services.edgar_ingestion import (
    EDGARIngestionService,
    calculate_sync_window,
    extract_submission_documents,
)


MASTER_INDEX = """Description:           Master Index of EDGAR Dissemination Feed
Last Data Received:    July 10, 2026
Comments:              webmaster@sec.gov

CIK|Company Name|Form Type|Date Filed|Filename
1000045|NICHOLAS FINANCIAL INC|10-Q|20260710|edgar/data/1000045/0000950170-26-100001.txt
320193|APPLE INC|8-K/A|2026-07-10|edgar/data/320193/0000320193-26-000050.txt
invalid|BROKEN|8-K|not-a-date|missing.txt
"""


SGML_SUBMISSION = b"""
<DOCUMENT>
<TYPE>8-K
<SEQUENCE>1
<FILENAME>company-8k.htm
<DESCRIPTION>CURRENT REPORT
<TEXT><html><body>Item 1.01 Entry into a Material Definitive Agreement</body></html></TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-10.1
<SEQUENCE>2
<FILENAME>license.htm
<DESCRIPTION>LICENSE AGREEMENT
<TEXT><html><body>Exclusive license agreement text.</body></html></TEXT>
</DOCUMENT>
<DOCUMENT>
<TYPE>EX-101.INS
<SEQUENCE>3
<FILENAME>xbrl.xml
<TEXT><xml>ignored</xml></TEXT>
</DOCUMENT>
"""


def test_parse_master_index():
    filings = parse_master_index(MASTER_INDEX)

    assert len(filings) == 2
    assert filings[0]["accession_number"] == "0000950170-26-100001"
    assert filings[1]["cik"] == "320193"
    assert filings[1]["url"].endswith("0000320193-26-000050.txt")


def test_priority_forms_include_amendments():
    assert is_priority_form("8-K")
    assert is_priority_form("8-K/A")
    assert is_priority_form("SC 13D/A")
    assert not is_priority_form("4")


def test_extract_submission_primary_and_priority_exhibits():
    documents = extract_submission_documents(SGML_SUBMISSION, "8-K")

    assert [document["doc_type"] for document in documents] == ["8-K", "EX-10.1"]
    assert documents[0]["is_primary"] is True
    assert documents[1]["filename"] == "license.htm"


def test_extract_submission_falls_back_for_unwrapped_payload():
    documents = extract_submission_documents(b"plain filing text", "6-K")

    assert len(documents) == 1
    assert documents[0]["doc_type"] == "6-K"
    assert documents[0]["content"] == b"plain filing text"


def test_calculate_sync_window_backfills_in_bounded_batches():
    window = calculate_sync_window(
        cursor=date(2026, 1, 31),
        target=date(2026, 2, 28),
        batch_days=7,
        overlap_days=3,
    )

    assert window.start == date(2026, 2, 1)
    assert window.end == date(2026, 2, 7)


def test_calculate_sync_window_replays_overlap_when_caught_up():
    window = calculate_sync_window(
        cursor=date(2026, 7, 10),
        target=date(2026, 7, 10),
        batch_days=7,
        overlap_days=3,
    )

    assert window.start == date(2026, 7, 8)
    assert window.end == date(2026, 7, 10)


@pytest.mark.asyncio
async def test_daily_index_404_is_an_empty_day():
    client = EDGARClient(user_agent="OneBD tests@example.org")
    request = httpx.Request("GET", "https://www.sec.gov/example")
    response = httpx.Response(404, request=request)
    client._rate_limited_request = AsyncMock(
        side_effect=httpx.HTTPStatusError("not found", request=request, response=response)
    )

    assert await client.get_daily_index(date(2026, 7, 4)) == []


@pytest.mark.asyncio
async def test_daily_index_403_is_an_empty_day():
    client = EDGARClient(user_agent="OneBD tests@example.org")
    request = httpx.Request("GET", "https://www.sec.gov/example")
    response = httpx.Response(403, request=request)
    client._rate_limited_request = AsyncMock(
        side_effect=httpx.HTTPStatusError("missing", request=request, response=response)
    )

    assert await client.get_daily_index(date(2026, 7, 4)) == []


class FakeClient:
    def __init__(self, filings_by_date):
        self.filings_by_date = filings_by_date

    async def get_daily_index(self, filing_date):
        return self.filings_by_date.get(filing_date, [])


class MemoryIngestionService(EDGARIngestionService):
    def __init__(self, client, cursor):
        super().__init__(client=client, session_context=None, embed_chunks=False)
        self.cursor = cursor
        self.advanced = []
        self.finished = None
        self.processed = []

    def ensure_sync_state(self, initial_target):
        pass

    def ensure_recent_sync_state(self):
        pass

    def get_cursor(self):
        return self.cursor

    def load_tracked_companies(self):
        return {"320193": 42}

    def mark_running(self):
        pass

    def mark_recent_running(self, window):
        self.recent_window = window

    def advance_cursor(self, completed_date):
        self.advanced.append(completed_date)

    def finish(self, status, stats, error=None):
        self.finished = (status, stats, error)

    def finish_recent(self, status, stats, error=None):
        self.finished = (status, stats, error)

    def filing_is_known(self, accession_number, form):
        return False

    async def process_filing(self, filing, company_id):
        self.processed.append((filing["accession_number"], company_id))
        return {"status": "fetched", "documents": 2, "chunks": 5, "embedded": 5}


@pytest.mark.asyncio
async def test_incremental_sync_filters_companies_and_advances_empty_days():
    filing_date = date(2026, 7, 9)
    filings = parse_master_index(MASTER_INDEX)
    service = MemoryIngestionService(
        FakeClient({filing_date: filings}),
        cursor=date(2026, 7, 8),
    )

    result = await service.sync_incremental(
        now=datetime(2026, 7, 11, tzinfo=timezone.utc),
        batch_days=2,
        overlap_days=1,
        max_filings=10,
    )

    assert result["status"] == "completed"
    assert result["filings_seen"] == 1
    assert result["filings_fetched"] == 1
    assert result["documents_created"] == 2
    assert service.processed == [("0000320193-26-000050", 42)]
    assert service.advanced == [date(2026, 7, 9), date(2026, 7, 10)]


@pytest.mark.asyncio
async def test_recent_sync_ignores_backfill_cursor_and_does_not_advance_it():
    filing_date = date(2026, 7, 10)
    filings = parse_master_index(MASTER_INDEX)
    service = MemoryIngestionService(
        FakeClient({filing_date: filings}),
        cursor=date(2025, 11, 23),
    )

    result = await service.sync_recent(
        now=datetime(2026, 7, 11, tzinfo=timezone.utc),
        recent_days=3,
        max_filings=10,
    )

    assert result["lane"] == "recent"
    assert result["window_start"] == "2026-07-08"
    assert result["window_end"] == "2026-07-10"
    assert result["filings_fetched"] == 1
    assert service.processed == [("0000320193-26-000050", 42)]
    assert service.advanced == []


def test_celery_task_runs_ingestion_service():
    expected = {"status": "completed", "filings_fetched": 3}
    with patch(
        "unified_api.services.edgar_ingestion.run_edgar_recent_sync",
        new=AsyncMock(return_value=expected),
    ):
        from unified_api.workers.celery_app import fetch_new_filings

        assert fetch_new_filings.run() == expected


def test_celery_backfill_task_runs_backfill_service():
    expected = {"status": "completed", "lane": "backfill", "filings_fetched": 3}
    with patch(
        "unified_api.services.edgar_ingestion.run_edgar_sync",
        new=AsyncMock(return_value=expected),
    ):
        from unified_api.workers.celery_app import backfill_edgar_filings

        assert backfill_edgar_filings.run() == expected
