"""
Comp Builder endpoints — find comparable deals and manage comp sets.
"""
from typing import Optional, List
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.comp_builder import score_deal_similarity, compute_comp_stats

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["comps"])


class CompBuildRequest(BaseModel):
    indication: Optional[str] = None
    phase: Optional[str] = None
    modality: Optional[str] = None
    deal_type: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    limit: int = 20


class CompSaveRequest(BaseModel):
    name: str
    deal_ids: List[int]
    criteria: Optional[dict] = None
    notes: Optional[str] = None


def build_comp_filters(req: CompBuildRequest) -> tuple[list[str], dict]:
    """Build candidate filters so every requested comp dimension is enforced."""
    conditions: list[str] = []
    params: dict = {"limit": min(req.limit * 3, 100)}

    if req.indication:
        conditions.append("""
            d.id IN (
                SELECT di.deal_id FROM deal_indications di
                JOIN indications i ON i.id = di.indication_id
                WHERE i.name ILIKE :indication
            )
        """)
        params["indication"] = f"%{req.indication}%"

    if req.phase:
        conditions.append("d.phase_highest_start ILIKE :phase")
        params["phase"] = f"%{req.phase}%"

    if req.modality:
        conditions.append("""
            d.id IN (
                SELECT dt.deal_id FROM deal_technologies dt
                JOIN technologies t ON t.id = dt.technology_id
                WHERE t.name ILIKE :modality
            )
        """)
        params["modality"] = f"%{req.modality}%"

    if req.deal_type:
        conditions.append("d.agreement_type ILIKE :deal_type")
        params["deal_type"] = f"%{req.deal_type}%"

    if req.date_from:
        conditions.append("d.date_start >= :date_from")
        params["date_from"] = req.date_from

    if req.date_to:
        conditions.append("d.date_start <= :date_to")
        params["date_to"] = req.date_to

    return conditions, params


def build_comp_dimension_selects(req: CompBuildRequest) -> tuple[str, str]:
    """Return the requested matching dimension instead of an arbitrary linked value."""
    indication_filter = " AND i.name ILIKE :indication" if req.indication else ""
    modality_filter = " AND t.name ILIKE :modality" if req.modality else ""
    indication_select = f"""(
        SELECT i.name FROM deal_indications di
        JOIN indications i ON i.id = di.indication_id
        WHERE di.deal_id = d.id{indication_filter}
        ORDER BY i.name LIMIT 1
    ) as indication"""
    modality_select = f"""(
        SELECT t.name FROM deal_technologies dt
        JOIN technologies t ON t.id = dt.technology_id
        WHERE dt.deal_id = d.id{modality_filter}
        ORDER BY t.name LIMIT 1
    ) as modality"""
    return indication_select, modality_select


@router.post("/comps/build")
async def build_comps(req: CompBuildRequest):
    """
    Find comparable deals based on criteria and rank by similarity.
    """
    with get_cortellis_session() as session:
        # Build query to find candidate deals
        conditions, params = build_comp_filters(req)
        indication_select, modality_select = build_comp_dimension_selects(req)

        where = " AND ".join(conditions) if conditions else "1=1"

        result = session.execute(text(f"""
            SELECT
                d.id, d.title, d.agreement_type, d.status,
                d.date_start::text, d.phase_highest_start,
                f.total_projected_current_amount as total_value,
                (SELECT c.name FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal,
                (SELECT c.name FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner,
                {indication_select},
                {modality_select}
            FROM deals d
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE {where}
            ORDER BY f.total_projected_current_amount DESC NULLS LAST
            LIMIT :limit
        """), params)

        candidates = []
        criteria = {
            k: v for k, v in {
                "indication": req.indication,
                "phase": req.phase,
                "modality": req.modality,
                "deal_type": req.deal_type,
            }.items() if v
        }

        for row in result:
            deal = {
                "id": row.id,
                "title": row.title,
                "agreement_type": row.agreement_type,
                "status": row.status,
                "date_start": row.date_start,
                "phase": row.phase_highest_start,
                "total_value": float(row.total_value) if row.total_value else None,
                "principal_company": row.principal,
                "partner_company": row.partner,
                "indication": row.indication,
                "modality": row.modality,
            }
            deal["match_score"] = score_deal_similarity(criteria, deal)
            candidates.append(deal)

        # Sort by match score, take top N
        candidates.sort(key=lambda d: d["match_score"], reverse=True)
        top_deals = candidates[:req.limit]

        stats = compute_comp_stats(top_deals)

    return {
        "criteria": criteria,
        "deals": top_deals,
        "stats": stats,
    }


@router.post("/comps", status_code=201)
async def save_comp_set(req: CompSaveRequest):
    """Save a comp set for future reference."""
    with get_cortellis_session() as session:
        # Ensure table exists
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS comp_sets (
                id SERIAL PRIMARY KEY,
                user_id INT DEFAULT 1,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                criteria JSONB,
                deal_ids INT[] NOT NULL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))

        import json
        result = session.execute(text("""
            INSERT INTO comp_sets (name, criteria, deal_ids, notes)
            VALUES (:name, :criteria, :deal_ids, :notes)
            RETURNING id
        """), {
            "name": req.name,
            "criteria": json.dumps(req.criteria) if req.criteria else None,
            "deal_ids": req.deal_ids,
            "notes": req.notes,
        })
        comp_id = result.fetchone()[0]
        session.commit()

    return {"id": comp_id, "name": req.name}


@router.get("/comps")
async def list_comp_sets():
    """List saved comp sets."""
    with get_cortellis_session() as session:
        # Check if table exists
        exists = session.execute(text("""
            SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'comp_sets')
        """)).scalar()

        if not exists:
            return []

        result = session.execute(text("""
            SELECT id, name, criteria, deal_ids, notes, created_at::text
            FROM comp_sets
            ORDER BY created_at DESC
            LIMIT 50
        """))

        return [
            {
                "id": row.id,
                "name": row.name,
                "criteria": row.criteria,
                "deal_ids": row.deal_ids,
                "notes": row.notes,
                "created_at": row.created_at,
            }
            for row in result
        ]
