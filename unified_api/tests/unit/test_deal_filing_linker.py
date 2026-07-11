"""Tests for the cross-database bulk deal/filing join."""

from datetime import date

from unified_api.services.deal_filing_linker import build_bulk_deal_filing_links


def test_bulk_linker_filters_company_and_date_and_ranks_nearest():
    deals = [{
        "deal_id": 10,
        "cortellis_company_id": 1,
        "date_start": date(2026, 1, 15),
    }]
    filings = [
        {"doc_id": 101, "edgar_company_id": 1001, "doc_type": "8-K", "filing_date": date(2026, 1, 15)},
        {"doc_id": 102, "edgar_company_id": 1001, "doc_type": "10-Q", "filing_date": date(2026, 1, 20)},
        {"doc_id": 103, "edgar_company_id": 1001, "doc_type": "8-K", "filing_date": date(2026, 3, 1)},
        {"doc_id": 104, "edgar_company_id": 2002, "doc_type": "8-K", "filing_date": date(2026, 1, 15)},
    ]

    links = build_bulk_deal_filing_links(deals, filings, {1: 1001})

    assert [link["doc_id"] for link in links] == [101, 102]
    assert links[0]["days_diff"] == 0
    assert links[0]["confidence"] == 1.0
    assert links[1]["days_diff"] == 5


def test_bulk_linker_limits_candidates_and_skips_existing_pairs():
    deals = [{
        "deal_id": 10,
        "cortellis_company_id": 1,
        "date_start": date(2026, 1, 15),
    }]
    filings = [
        {
            "doc_id": doc_id,
            "edgar_company_id": 1001,
            "doc_type": "8-K",
            "filing_date": date(2026, 1, 15 + offset),
        }
        for offset, doc_id in enumerate((100, 101, 102, 103))
    ]

    links = build_bulk_deal_filing_links(
        deals,
        filings,
        {1: 1001},
        existing_pairs={(10, 100)},
        max_filings_per_deal=3,
    )

    assert [link["doc_id"] for link in links] == [101, 102]


def test_bulk_linker_does_not_duplicate_same_deal_document_pair():
    deals = [
        {"deal_id": 10, "cortellis_company_id": 1, "date_start": date(2026, 1, 15)},
        {"deal_id": 10, "cortellis_company_id": 1, "date_start": date(2026, 1, 15)},
    ]
    filings = [{
        "doc_id": 101,
        "edgar_company_id": 1001,
        "doc_type": "8-K",
        "filing_date": date(2026, 1, 15),
    }]

    links = build_bulk_deal_filing_links(deals, filings, {1: 1001})

    assert len(links) == 1
