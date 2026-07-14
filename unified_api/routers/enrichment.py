"""Data enrichment endpoints — trigger and validate structured enrichments."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.routers.admin import require_admin
from unified_api.services.auth import TokenData
from unified_api.services.audit import log_audit
from unified_api.services.contract_financial_clauses import (
    contract_financial_clause_review_sample,
    contract_financial_clause_status,
    contract_financial_clause_validation_status,
    extract_contract_financial_clause_batch,
    review_contract_financial_clause,
)
from unified_api.services.deal_evidence_timeline import (
    deal_trial_link_validation_status,
    deal_trial_link_status,
    extract_deal_trial_link_batch,
)
from unified_api.services.cortellis_contract_sync import contract_scan_status
from unified_api.services.cortellis_deal_api_sync import deal_api_scan_status
from unified_api.services.financial_terms import (
    extract_financial_term_batch,
    financial_term_status,
    financial_term_validation_status,
)
from unified_api.services.pubchem_enrichment import (
    pubchem_enrichment_status,
    pubchem_validation_status,
)
from unified_api.services.public_drug_enrichment import (
    public_drug_enrichment_status,
)
from unified_api.services.uniprot_enrichment import uniprot_enrichment_status
from unified_api.services.europe_pmc_enrichment import europe_pmc_enrichment_status
from unified_api.services.sec_company_identity import (
    audit_sec_company_identities,
    sec_company_identity_status,
)
from unified_api.services.gleif_company_identity import (
    enrich_gleif_company_identities,
    enrich_gleif_company_ownership,
    gleif_company_identity_status,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["enrichment"])


class ContractFinancialClauseReview(BaseModel):
    review_status: Literal["accepted", "rejected"]
    note: str | None = Field(default=None, max_length=2000)


@router.post("/api/enrichment/parse-financials")
async def parse_financial_details(
    batch_size: int = Query(100, ge=1, le=1000),
    dry_run: bool = Query(False),
    force: bool = Query(False),
    _current_user: TokenData = Depends(require_admin),
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
    _current_user: TokenData = Depends(require_admin),
):
    """Extract explicit royalty, milestone, and upfront contract evidence."""
    with get_cortellis_session() as session:
        return extract_contract_financial_clause_batch(
            session,
            batch_size=batch_size,
            dry_run=dry_run,
            force=force,
        )


@router.post("/api/enrichment/link-deal-clinical-trials")
async def link_deal_clinical_trials(
    batch_size: int = Query(1000, ge=1, le=5000),
    _current_user: TokenData = Depends(require_admin),
):
    """Extract exact NCT citations from lossless Cortellis deal payloads."""
    with get_cortellis_session() as session:
        return extract_deal_trial_link_batch(session, batch_size=batch_size)


@router.post("/api/enrichment/audit-sec-company-identities")
async def audit_sec_company_identity_batch(
    batch_size: int = Query(100, ge=1, le=500),
    refresh: bool = Query(False),
    _current_user: TokenData = Depends(require_admin),
):
    """Verify CIK ownership before retaining SEC-reported identity fields."""
    return audit_sec_company_identities(
        batch_size=batch_size,
        refresh=refresh,
    )


@router.get("/api/enrichment/company-identities/status")
async def company_identity_enrichment_status():
    """Return CIK audit coverage, mismatches, and retained identifiers."""
    return sec_company_identity_status()


@router.post("/api/enrichment/gleif-company-identities")
async def enrich_gleif_company_identity_batch(
    batch_size: int = Query(25, ge=1, le=100),
    refresh: bool = Query(False),
    _current_user: TokenData = Depends(require_admin),
):
    """Retain unique exact-name GLEIF LEI matches with full provenance."""
    return enrich_gleif_company_identities(
        batch_size=batch_size,
        refresh=refresh,
    )


@router.post("/api/enrichment/gleif-company-ownership")
async def enrich_gleif_company_ownership_batch(
    batch_size: int = Query(50, ge=1, le=100),
    refresh: bool = Query(False),
    _current_user: TokenData = Depends(require_admin),
):
    """Retain GLEIF Level 2 direct parents that map to local LEIs."""
    return enrich_gleif_company_ownership(
        batch_size=batch_size,
        refresh=refresh,
    )


@router.get("/api/enrichment/gleif-company-identities/status")
async def gleif_company_enrichment_status():
    """Return GLEIF LEI and ownership coverage/review status."""
    return gleif_company_identity_status()


@router.get("/api/enrichment/status")
async def enrichment_status():
    """Get current enrichment status across all data sources."""
    with get_cortellis_session() as session:
        finance_status = financial_term_status(session)
        contract_clause_status = contract_financial_clause_status(session)
        deal_trial_status = deal_trial_link_status(session)
    contract_metadata_status = contract_scan_status()
    deal_api_status = deal_api_scan_status()
    pubchem_status = pubchem_enrichment_status()
    public_drug_status = public_drug_enrichment_status()
    uniprot_status = uniprot_enrichment_status()
    europe_pmc_status = europe_pmc_enrichment_status()
    company_identity_status = sec_company_identity_status()
    gleif_identity_status = gleif_company_identity_status()

    return {
        "finance_enrichment": finance_status,
        "contract_financial_clause_enrichment": contract_clause_status,
        "exact_deal_clinical_trial_links": deal_trial_status,
        "cortellis_contract_metadata_scan": contract_metadata_status,
        "cortellis_deal_api_scan": deal_api_status,
        "pubchem_enrichment": pubchem_status,
        "public_drug_target_enrichment": public_drug_status,
        "uniprot_target_enrichment": uniprot_status,
        "europe_pmc_target_literature_enrichment": europe_pmc_status,
        "sec_company_identity_enrichment": company_identity_status,
        "gleif_company_identity_enrichment": gleif_identity_status,
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


@router.get("/api/enrichment/pubchem/validation")
async def pubchem_validation(
    sample_limit: int = Query(25, ge=1, le=100),
):
    """Return PubChem coverage, identifier integrity, and review samples."""
    return {
        "pubchem_validation": pubchem_validation_status(
            sample_limit=sample_limit,
        )
    }


@router.get("/api/enrichment/contract-financial-clauses/validation")
async def contract_financial_clause_validation(
    sample_per_type: int = Query(25, ge=1, le=100),
    _current_user: TokenData = Depends(require_admin),
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


@router.get("/api/enrichment/deal-clinical-trials/validation")
async def deal_clinical_trial_link_validation(
    _current_user: TokenData = Depends(require_admin),
):
    """Validate exact NCT IDs, archived offsets/hashes, and registry matches."""
    with get_cortellis_session() as session:
        return {
            "deal_clinical_trial_link_validation": (
                deal_trial_link_validation_status(session)
            )
        }


@router.get("/api/enrichment/contract-financial-clauses/review-sample")
async def contract_financial_clause_sample(
    limit: int = Query(100, ge=1, le=500),
    _current_user: TokenData = Depends(require_admin),
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
    current_user: TokenData = Depends(require_admin),
):
    """Accept or reject one candidate with reviewer provenance."""
    with get_cortellis_session() as session:
        reviewed = review_contract_financial_clause(
            session,
            clause_id=clause_id,
            review_status=request.review_status,
            reviewer=current_user.email,
            note=request.note,
        )
    if reviewed is None:
        raise HTTPException(status_code=404, detail="Clause candidate not found")
    log_audit(
        "contract_financial_clause_review",
        user_id=current_user.user_id,
        entity_type="contract_financial_clause",
        entity_id=str(clause_id),
        metadata={
            "review_status": request.review_status,
            "parser_version": reviewed["review_parser_version"],
        },
    )
    return reviewed
