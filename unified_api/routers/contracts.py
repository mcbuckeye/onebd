"""
Contract Intelligence endpoints.

Clause extraction, term comparison, and contract analysis.
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Path
from pydantic import BaseModel
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()


# ============================================
# Clause Extraction
# ============================================

class ClauseExtractionRequest(BaseModel):
    """Request to extract clauses from a contract."""
    deal_id: Optional[int] = None
    text: Optional[str] = None  # Provide text directly, or use deal_id to fetch


@router.post("/contracts/extract-clauses")
async def extract_contract_clauses(request: ClauseExtractionRequest):
    """
    Extract structured deal terms from contract text using GPT-4o.

    Either provide contract text directly or a deal_id to fetch from database.

    Extracts:
    - Upfront payments
    - Royalty rates and tiers
    - Milestone payments (clinical, regulatory, commercial)
    - License scope and exclusivity
    - Territory rights
    - Term duration and termination provisions
    """
    from unified_api.services.clause_extractor import extract_clauses

    contract_text = request.text

    if not contract_text and request.deal_id:
        # Fetch contract text from database
        from sqlalchemy import text
        from unified_api.services.database import get_cortellis_session

        with get_cortellis_session() as session:
            result = session.execute(text("""
                SELECT content FROM contract_content
                WHERE deal_id = :deal_id
            """), {"deal_id": request.deal_id})
            row = result.fetchone()

            if not row:
                raise HTTPException(
                    status_code=404,
                    detail=f"No contract found for deal {request.deal_id}"
                )
            contract_text = row.content

    if not contract_text:
        raise HTTPException(status_code=400, detail="Provide either text or deal_id")

    result = await extract_clauses(contract_text, deal_id=request.deal_id)
    return result


@router.get("/contracts/{deal_id}/clauses")
async def get_deal_clauses(
    deal_id: int = Path(..., gt=0),
    force_reextract: bool = Query(False, description="Re-extract even if cached"),
):
    """
    Get extracted clauses for a deal's contract.

    First checks for cached extraction, then runs extraction if needed.
    Results are stored in contract_content.extracted_clauses for future use.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    with get_cortellis_session() as session:
        # Check if contract exists
        contract = session.execute(text("""
            SELECT deal_id, content,
                   LENGTH(content) as content_length
            FROM contract_content
            WHERE deal_id = :deal_id
        """), {"deal_id": deal_id}).fetchone()

        if not contract:
            raise HTTPException(
                status_code=404,
                detail=f"No contract found for deal {deal_id}"
            )

    if not contract.content or len(contract.content.strip()) < 100:
        return {
            "deal_id": deal_id,
            "status": "insufficient_content",
            "content_length": contract.content_length,
            "clauses": None,
        }

    # Extract clauses
    from unified_api.services.clause_extractor import extract_clauses
    clauses = await extract_clauses(contract.content, deal_id=deal_id)

    return {
        "deal_id": deal_id,
        "status": "extracted",
        "content_length": contract.content_length,
        "clauses": clauses,
    }


# ============================================
# Term Comparison
# ============================================

@router.get("/contracts/compare")
async def compare_deal_terms(
    deal_ids: str = Query(..., description="Comma-separated deal IDs (2-5)"),
):
    """
    Compare contract terms side-by-side for multiple deals.

    Returns a structured comparison of key deal terms including
    financial terms, license scope, and territory rights.
    Useful for benchmarking deals.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    ids = [int(x.strip()) for x in deal_ids.split(",") if x.strip().isdigit()][:5]

    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 deal IDs")

    logger.info("Comparing deal terms", deal_ids=ids)

    with get_cortellis_session() as session:
        deals = []
        for deal_id in ids:
            # Get deal info
            deal = session.execute(text("""
                SELECT
                    d.id, d.title, d.agreement_type, d.status,
                    d.date_start::text,
                    f.total_projected_current_amount as total_value,
                    f.total_paid_amount as total_paid,
                    f.total_projected_signing_amount as signing_value,
                    f.total_projected_current_disclosure_status as disclosure_status,
                    (SELECT c.name FROM deal_companies dc
                     JOIN companies c ON c.id = dc.company_id
                     WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal,
                    (SELECT c.name FROM deal_companies dc
                     JOIN companies c ON c.id = dc.company_id
                     WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner,
                    (SELECT string_agg(i.name, ', ')
                     FROM deal_indications di
                     JOIN indications i ON i.id = di.indication_id
                     WHERE di.deal_id = d.id) as indications,
                    (SELECT string_agg(t.name, ', ')
                     FROM deal_territories dt
                     JOIN territories t ON t.id = dt.territory_id
                     WHERE dt.deal_id = d.id) as territories,
                    d.has_contract
                FROM deals d
                LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
                WHERE d.id = :deal_id
            """), {"deal_id": deal_id}).fetchone()

            if not deal:
                continue

            # Get timeline events (milestones)
            events = session.execute(text("""
                SELECT stage, event_type, event_date::text, summary,
                       payments_to_principal, payments_to_partner
                FROM deal_timeline_events
                WHERE deal_id = :deal_id
                ORDER BY event_date
            """), {"deal_id": deal_id})

            milestones = [
                {
                    "stage": e.stage,
                    "event_type": e.event_type,
                    "date": e.event_date,
                    "summary": e.summary[:200] if e.summary else None,
                    "payments_to_principal": e.payments_to_principal,
                    "payments_to_partner": e.payments_to_partner,
                }
                for e in events
            ]

            # Get drugs
            drugs = session.execute(text("""
                SELECT dr.name_display as name, dr.phase_highest_now as phase
                FROM deal_drugs dd
                JOIN drugs dr ON dr.id = dd.drug_id
                WHERE dd.deal_id = :deal_id
            """), {"deal_id": deal_id})

            drug_list = [
                {"name": dr.name, "phase": dr.phase}
                for dr in drugs
            ]

            deals.append({
                "id": deal.id,
                "title": deal.title,
                "agreement_type": deal.agreement_type,
                "status": deal.status,
                "date_start": deal.date_start,
                "principal": deal.principal,
                "partner": deal.partner,
                "financials": {
                    "total_projected_value": float(deal.total_value) if deal.total_value else None,
                    "total_paid": float(deal.total_paid) if deal.total_paid else None,
                    "signing_value": float(deal.signing_value) if deal.signing_value else None,
                    "disclosure_status": deal.disclosure_status,
                },
                "indications": deal.indications,
                "territories": deal.territories,
                "has_contract": deal.has_contract,
                "drugs": drug_list,
                "milestones": milestones,
            })

    if len(deals) < 2:
        raise HTTPException(status_code=404, detail="Could not find enough deals to compare")

    # Build comparison summary
    comparison = {
        "deal_count": len(deals),
        "deals": deals,
        "value_comparison": {
            "values": [
                {
                    "deal_id": d["id"],
                    "title": d["title"][:60],
                    "total_value": d["financials"]["total_projected_value"],
                }
                for d in deals
            ],
            "highest": max(
                [d for d in deals if d["financials"]["total_projected_value"]],
                key=lambda x: x["financials"]["total_projected_value"] or 0,
                default=None,
            ),
        },
        "common_indications": None,
    }

    # Find common indications
    ind_sets = [set(d["indications"].split(", ")) if d["indications"] else set() for d in deals]
    if all(ind_sets):
        common = ind_sets[0].intersection(*ind_sets[1:])
        if common:
            comparison["common_indications"] = list(common)

    return comparison
