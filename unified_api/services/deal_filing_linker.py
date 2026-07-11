"""Bulk in-memory join primitives for Cortellis deals and EDGAR filings."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Iterable, Mapping


def _date_only(value: date | datetime) -> date:
    return value.date() if isinstance(value, datetime) else value


def build_bulk_deal_filing_links(
    deals: Iterable[Mapping],
    filings: Iterable[Mapping],
    xref_map: Mapping[int, int],
    *,
    existing_pairs: set[tuple[int, int]] | None = None,
    window_days: int = 30,
    max_filings_per_deal: int = 10,
) -> list[dict]:
    """Match two bulk result sets without issuing a query for every deal."""
    existing_pairs = existing_pairs or set()
    by_company: dict[int, list[tuple[date, Mapping]]] = defaultdict(list)
    for filing in filings:
        filing_date = filing.get("filing_date")
        if filing_date is None:
            continue
        by_company[int(filing["edgar_company_id"])].append(
            (_date_only(filing_date), filing)
        )
    for company_filings in by_company.values():
        company_filings.sort(key=lambda item: (item[0], int(item[1]["doc_id"])))

    links: list[dict] = []
    emitted = set(existing_pairs)
    window = timedelta(days=window_days)
    for deal in deals:
        deal_date_value = deal.get("date_start")
        edgar_company_id = xref_map.get(int(deal["cortellis_company_id"]))
        if deal_date_value is None or edgar_company_id is None:
            continue
        deal_date = _date_only(deal_date_value)
        company_filings = by_company.get(edgar_company_id, [])
        if not company_filings:
            continue
        dates = [item[0] for item in company_filings]
        start = bisect_left(dates, deal_date - window)
        end = bisect_right(dates, deal_date + window)
        candidates = sorted(
            company_filings[start:end],
            key=lambda item: (
                abs((item[0] - deal_date).days),
                item[0],
                int(item[1]["doc_id"]),
            ),
        )[:max_filings_per_deal]
        for filing_date, filing in candidates:
            pair = (int(deal["deal_id"]), int(filing["doc_id"]))
            if pair in emitted:
                continue
            distance = abs((filing_date - deal_date).days)
            links.append({
                "deal_id": pair[0],
                "doc_id": pair[1],
                "edgar_company_id": edgar_company_id,
                "match_type": f"company_date_{filing['doc_type']}",
                "days_diff": distance,
                "confidence": max(0.3, 1.0 - (distance / window_days) * 0.5),
            })
            emitted.add(pair)
    return links
