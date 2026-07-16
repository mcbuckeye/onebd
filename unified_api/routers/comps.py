"""
Comp Builder endpoints — find comparable deals and manage comp sets.
"""
from datetime import date
from typing import Optional, List
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.comp_builder import score_deal_similarity, compute_comp_stats
from unified_api.services.auth import TokenData
from unified_api.routers.auth import get_current_user

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["comps"])


class CompBuildRequest(BaseModel):
    indication: Optional[str] = None
    phase: Optional[str] = None
    modality: Optional[str] = None
    deal_type: Optional[str] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    include_terminated: bool = False
    limit: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def validate_criteria(self):
        if not any(
            (
                self.indication,
                self.phase,
                self.modality,
                self.deal_type,
                self.date_from,
                self.date_to,
            )
        ):
            raise ValueError("At least one comparison criterion is required")
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from cannot be after date_to")
        return self


class CompSaveRequest(BaseModel):
    name: str
    deal_ids: List[int]
    criteria: Optional[dict] = None
    notes: Optional[str] = None


def migrate_comp_sets_schema(session) -> None:
    """Create user-scoped saved comp storage during deployment migration."""
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS comp_sets (
            id SERIAL PRIMARY KEY,
            user_id INT NOT NULL,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            criteria JSONB,
            deal_ids INT[] NOT NULL,
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    session.execute(text("""
        ALTER TABLE comp_sets ADD COLUMN IF NOT EXISTS user_id INT;
        UPDATE comp_sets SET user_id = 1 WHERE user_id IS NULL;
        ALTER TABLE comp_sets ALTER COLUMN user_id SET NOT NULL;
        ALTER TABLE comp_sets ALTER COLUMN user_id DROP DEFAULT;
        CREATE INDEX IF NOT EXISTS ix_comp_sets_user_created
          ON comp_sets (user_id, created_at DESC)
    """))


def _modality_patterns(value: str) -> list[str]:
    """Expand common shorthand without pretending it is a canonical taxonomy."""
    normalized = value.strip().lower().replace("_", " ")
    aliases = {
        "adc": ["adc", "antibody-drug conjugate", "antibody drug conjugate"],
        "antibody drug conjugate": [
            "adc",
            "antibody-drug conjugate",
            "antibody drug conjugate",
        ],
        "antibody-drug conjugate": [
            "adc",
            "antibody-drug conjugate",
            "antibody drug conjugate",
        ],
    }
    return [f"%{item}%" for item in aliases.get(normalized, [value.strip()])]


def _indication_patterns(value: str) -> list[str]:
    """Expand common clinical abbreviations into source-taxonomy spellings."""
    normalized = value.strip().lower().replace("_", " ")
    aliases = {
        "nsclc": ["nsclc", "non%small%cell%lung%cancer"],
        "non small cell lung cancer": [
            "nsclc",
            "non%small%cell%lung%cancer",
        ],
        "sclc": ["sclc", "small%cell%lung%cancer"],
        "aml": ["aml", "acute%myeloid%leukemia", "acute%myelogenous%leukemia"],
        "dlbcl": ["dlbcl", "diffuse%large%b%cell%lymphoma"],
        "tnbc": ["tnbc", "triple%negative%breast%cancer"],
        "rcc": ["rcc", "renal%cell%carcinoma"],
    }
    return [f"%{item}%" for item in aliases.get(normalized, [value.strip()])]


def _modality_match_sql(column: str) -> str:
    return f"{column} ILIKE ANY(CAST(:modality_patterns AS text[]))"


def _indication_match_sql(column: str) -> str:
    return f"{column} ILIKE ANY(CAST(:indication_patterns AS text[]))"


def build_comp_filters(req: CompBuildRequest) -> tuple[list[str], dict]:
    """Build candidate filters so every requested comp dimension is enforced."""
    conditions: list[str] = []
    params: dict = {"limit": min(req.limit * 3, 100)}

    if req.indication:
        conditions.append("""
            d.id IN (
                SELECT di.deal_id FROM deal_indications di
                JOIN indications i ON i.id = di.indication_id
                WHERE i.name ILIKE ANY(CAST(:indication_patterns AS text[]))
            )
        """)
        params["indication_patterns"] = _indication_patterns(req.indication)

    if req.phase:
        conditions.append("d.phase_highest_start ILIKE :phase")
        params["phase"] = f"%{req.phase}%"

    if req.modality:
        conditions.append("""
            (d.id IN (
                SELECT dt.deal_id
                FROM deal_technologies dt
                JOIN technologies t ON t.id = dt.technology_id
                WHERE t.name ILIKE ANY(CAST(:modality_patterns AS text[]))
            ) OR d.id IN (
                SELECT dd.deal_id
                FROM deal_drugs dd
                WHERE EXISTS (
                    SELECT 1 FROM public_drug_profiles p
                    WHERE p.drug_id = dd.drug_id
                      AND p.drug_type ILIKE ANY(CAST(:modality_patterns AS text[]))
                ) OR EXISTS (
                    SELECT 1 FROM drug_chembl_records cr
                    WHERE cr.drug_id = dd.drug_id
                      AND cr.molecule_type ILIKE ANY(CAST(:modality_patterns AS text[]))
                )
            ))
        """)
        params["modality_patterns"] = _modality_patterns(req.modality)

    if req.deal_type:
        conditions.append("d.agreement_type ILIKE :deal_type")
        params["deal_type"] = f"%{req.deal_type}%"

    if req.date_from:
        conditions.append("d.date_start >= :date_from")
        params["date_from"] = req.date_from

    if req.date_to:
        conditions.append("d.date_start <= :date_to")
        params["date_to"] = req.date_to

    if not req.include_terminated:
        conditions.append("""
            COALESCE(d.status, '') NOT ILIKE ALL(
                ARRAY['%terminated%', '%withdrawn%', '%cancelled%', '%canceled%', '%failed%']
            )
        """)

    return conditions, params


def build_comp_dimension_selects(req: CompBuildRequest) -> tuple[str, str]:
    """Return the requested matching dimension instead of an arbitrary linked value."""
    indication_filter = (
        " AND " + _indication_match_sql("i.name") if req.indication else ""
    )
    modality_filter = (
        " AND " + _modality_match_sql("t.name") if req.modality else ""
    )
    indication_select = f"""(
        SELECT i.name FROM deal_indications di
        JOIN indications i ON i.id = di.indication_id
        WHERE di.deal_id = d.id{indication_filter}
        ORDER BY i.name LIMIT 1
    ) as indication"""
    public_profile_filter = (
        " AND " + _modality_match_sql("p.drug_type") if req.modality else ""
    )
    chembl_filter = (
        " AND " + _modality_match_sql("cr.molecule_type") if req.modality else ""
    )
    modality_select = f"""COALESCE(
        (SELECT t.name FROM deal_technologies dt
         JOIN technologies t ON t.id = dt.technology_id
         WHERE dt.deal_id = d.id{modality_filter}
         ORDER BY t.name LIMIT 1),
        (SELECT p.drug_type FROM deal_drugs dd
         JOIN public_drug_profiles p ON p.drug_id = dd.drug_id
         WHERE dd.deal_id = d.id{public_profile_filter}
         ORDER BY p.drug_type LIMIT 1),
        (SELECT cr.molecule_type FROM deal_drugs dd
         JOIN drug_chembl_records cr ON cr.drug_id = dd.drug_id
         WHERE dd.deal_id = d.id{chembl_filter}
         ORDER BY cr.molecule_type LIMIT 1)
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
              AND f.total_projected_current_currency = 'USD'
              AND f.total_projected_current_unit = 'Million'
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
                "total_value": float(row.total_value) if row.total_value is not None else None,
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
async def save_comp_set(
    req: CompSaveRequest,
    user: TokenData = Depends(get_current_user),
):
    """Save a comp set for future reference."""
    with get_cortellis_session() as session:
        import json
        result = session.execute(text("""
            INSERT INTO comp_sets (user_id, name, criteria, deal_ids, notes)
            VALUES (:user_id, :name, :criteria, :deal_ids, :notes)
            RETURNING id
        """), {
            "user_id": user.user_id,
            "name": req.name,
            "criteria": json.dumps(req.criteria) if req.criteria else None,
            "deal_ids": req.deal_ids,
            "notes": req.notes,
        })
        comp_id = result.fetchone()[0]
        session.commit()

    return {"id": comp_id, "name": req.name}


@router.get("/comps")
async def list_comp_sets(user: TokenData = Depends(get_current_user)):
    """List saved comp sets."""
    with get_cortellis_session() as session:
        result = session.execute(text("""
            SELECT id, name, criteria, deal_ids, notes, created_at::text
            FROM comp_sets
            WHERE user_id = :user_id
            ORDER BY created_at DESC
            LIMIT 50
        """), {"user_id": user.user_id})

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
