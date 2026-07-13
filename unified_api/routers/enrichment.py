"""Data enrichment endpoints — trigger and validate structured enrichments."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.contract_financial_clauses import (
    contract_financial_clause_review_sample,
    contract_financial_clause_status,
    contract_financial_clause_validation_status,
    extract_contract_financial_clause_batch,
    review_contract_financial_clause,
)
from unified_api.services.financial_terms import (
    extract_financial_term_batch,
    financial_term_status,
    financial_term_validation_status,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["enrichment"])


class ContractFinancialClauseReview(BaseModel):
    review_status: Literal["accepted", "rejected"]
    reviewer: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


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


@router.post("/api/enrichment/parse-contract-financial-clauses")
async def parse_contract_financial_clauses(
    batch_size: int = Query(500, ge=1, le=1000),
    dry_run: bool = Query(False),
    force: bool = Query(False),
):
    """Extract explicit royalty, milestone, and upfront contract evidence."""
    with get_cortellis_session() as session:
        return extract_contract_financial_clause_batch(
            session,
            batch_size=batch_size,
            dry_run=dry_run,
            force=force,
        )


@router.get("/api/enrichment/status")
async def enrichment_status():
    """Get current enrichment status across all data sources."""
    with get_cortellis_session() as session:
        finance_status = financial_term_status(session)
        contract_clause_status = contract_financial_clause_status(session)

    return {
        "finance_enrichment": finance_status,
        "contract_financial_clause_enrichment": contract_clause_status,
    }


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


@router.get("/api/enrichment/contract-financial-clauses/validation")
async def contract_financial_clause_validation(
    sample_per_type: int = Query(25, ge=1, le=100),
):
    """Return population, replay, and manual-review readiness checks."""
    with get_cortellis_session() as session:
        return {
            "contract_financial_clause_validation": (
                contract_financial_clause_validation_status(
                    session,
                    sample_per_type=sample_per_type,
                )
            )
        }


@router.get("/api/enrichment/contract-financial-clauses/review-sample")
async def contract_financial_clause_sample(
    limit: int = Query(100, ge=1, le=500),
):
    """Return a deterministic, type-balanced manual-review queue."""
    with get_cortellis_session() as session:
        return {
            "candidates": contract_financial_clause_review_sample(
                session,
                limit=limit,
            )
        }


@router.patch("/api/enrichment/contract-financial-clauses/{clause_id}/review")
async def review_contract_clause(
    clause_id: int,
    request: ContractFinancialClauseReview,
):
    """Accept or reject one candidate with reviewer provenance."""
    with get_cortellis_session() as session:
        reviewed = review_contract_financial_clause(
            session,
            clause_id=clause_id,
            review_status=request.review_status,
            reviewer=request.reviewer,
            note=request.note,
        )
    if reviewed is None:
        raise HTTPException(status_code=404, detail="Clause candidate not found")
    return reviewed
