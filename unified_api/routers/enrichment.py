"""
Data enrichment endpoints — trigger parsing and enrichment of raw data fields.
"""
from fastapi import APIRouter, Query
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.financial_terms import (
    extract_financial_term_batch,
    financial_term_status,
    financial_term_validation_status,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["enrichment"])


@router.post("/api/enrichment/parse-financials")
async def parse_financial_details(
    batch_size: int = Query(100, ge=1, le=1000),
    dry_run: bool = Query(False),
    force: bool = Query(False),
):
    """
    Parse finance_detail_raw fields into structured financial data.
    Processes deals that have raw finance text but haven't been parsed yet.
    """
    with get_cortellis_session() as session:
        return extract_financial_term_batch(
            session,
            batch_size=batch_size,
            dry_run=dry_run,
            force=force,
        )


@router.get("/api/enrichment/status")
async def enrichment_status():
    """Get current enrichment status across all data sources."""
    with get_cortellis_session() as session:
        status = financial_term_status(session)

    return {"finance_enrichment": status}


@router.get("/api/enrichment/financial-terms/validation")
async def financial_term_validation(
    sample_per_type: int = Query(25, ge=1, le=100),
):
    """Return a deterministic population and source-fidelity audit."""
    with get_cortellis_session() as session:
        return {
            "finance_enrichment_validation": financial_term_validation_status(
                session,
                sample_per_type=sample_per_type,
            )
        }
