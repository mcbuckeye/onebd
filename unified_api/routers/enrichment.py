"""
Data enrichment endpoints — trigger parsing and enrichment of raw data fields.
"""
from fastapi import APIRouter, Query
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.finance_parser import parse_finance_detail

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["enrichment"])


@router.post("/api/enrichment/parse-financials")
async def parse_financial_details(
    batch_size: int = Query(100, ge=1, le=1000),
    dry_run: bool = Query(False),
):
    """
    Parse finance_detail_raw fields into structured financial data.
    Processes deals that have raw finance text but haven't been parsed yet.
    """
    parsed_count = 0
    error_count = 0
    results_sample = []

    with get_cortellis_session() as session:
        # Check if the enrichment tracking column exists, create if not
        session.execute(text("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'deal_finance_summary'
                    AND column_name = 'parsed_detail'
                ) THEN
                    ALTER TABLE deal_finance_summary ADD COLUMN parsed_detail JSONB;
                END IF;
            END $$
        """))
        session.commit()

        # Get deals with finance detail text that haven't been parsed
        deals = session.execute(text("""
            SELECT f.deal_id, f.finance_detail_raw
            FROM deal_finance_summary f
            WHERE f.finance_detail_raw IS NOT NULL
              AND f.finance_detail_raw != ''
              AND f.parsed_detail IS NULL
            LIMIT :batch_size
        """), {"batch_size": batch_size}).fetchall()

        for deal in deals:
            try:
                parsed = parse_finance_detail(deal.finance_detail_raw)

                if not dry_run:
                    import json
                    session.execute(text("""
                        UPDATE deal_finance_summary
                        SET parsed_detail = :parsed
                        WHERE deal_id = :deal_id
                    """), {
                        "deal_id": deal.deal_id,
                        "parsed": json.dumps(parsed),
                    })

                parsed_count += 1

                if len(results_sample) < 5:
                    results_sample.append({
                        "deal_id": deal.deal_id,
                        "raw_text": deal.finance_detail_raw[:200],
                        "parsed": parsed,
                    })

            except Exception as e:
                error_count += 1
                logger.error("Failed to parse finance detail", deal_id=deal.deal_id, error=str(e))

        if not dry_run:
            session.commit()

    return {
        "processed": parsed_count,
        "errors": error_count,
        "dry_run": dry_run,
        "sample": results_sample,
        "remaining": "Use batch_size to process more",
    }


@router.get("/api/enrichment/status")
async def enrichment_status():
    """Get current enrichment status across all data sources."""
    with get_cortellis_session() as session:
        stats = session.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM deal_finance_summary WHERE finance_detail_raw IS NOT NULL) as has_raw_text,
                (SELECT COUNT(*) FROM deal_finance_summary WHERE parsed_detail IS NOT NULL) as has_parsed,
                (SELECT COUNT(*) FROM deal_finance_summary WHERE total_projected_current_amount IS NOT NULL) as has_amount,
                (SELECT COUNT(*) FROM deals) as total_deals
        """)).fetchone()

    return {
        "finance_enrichment": {
            "deals_with_raw_text": stats.has_raw_text,
            "deals_parsed": stats.has_parsed,
            "deals_with_amount": stats.has_amount,
            "total_deals": stats.total_deals,
            "parse_coverage": f"{(stats.has_parsed / stats.has_raw_text * 100):.1f}%" if stats.has_raw_text > 0 else "0%",
        },
    }
