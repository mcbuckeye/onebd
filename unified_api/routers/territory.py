"""Deal territory-scope evidence endpoints."""
from fastapi import APIRouter, HTTPException
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["territory"])


@router.get("/territory/{drug_id}/map")
async def get_territory_map(drug_id: int):
    """
    Get territory-scope evidence from deals involving a drug/asset.

    A territory listed on a deal is evidence about that agreement's scope. It
    is not, by itself, proof of current ownership, availability, exclusivity,
    or a rights holder.
    """
    with get_cortellis_session() as session:
        # Get drug info
        drug = session.execute(text("""
            SELECT id, name_display as name, phase_highest_now as phase
            FROM drugs WHERE id = :id
        """), {"id": drug_id}).fetchone()

        if not drug:
            raise HTTPException(status_code=404, detail="Drug not found")

        # Get territory data from deals involving this drug
        territories = session.execute(text("""
            SELECT DISTINCT
                t.name as territory,
                dt.territory_type as scope_type,
                d.id as deal_id,
                d.title as deal_title,
                d.status as deal_status,
                d.date_start::text as deal_date,
                (SELECT jsonb_agg(jsonb_build_object(
                    'id', participant.id,
                    'name', participant.name,
                    'role', link.role
                ) ORDER BY link.role, participant.name)
                 FROM deal_companies link
                 JOIN companies participant ON participant.id = link.company_id
                 WHERE link.deal_id = d.id) as participants
            FROM deal_drugs dd
            JOIN deals d ON d.id = dd.deal_id
            JOIN deal_territories dt ON dt.deal_id = d.id
            JOIN territories t ON t.id = dt.territory_id
            WHERE dd.drug_id = :drug_id
            ORDER BY t.name
        """), {"drug_id": drug_id}).fetchall()

        territory_list = []
        for t in territories:
            scope_type = (t.scope_type or "").strip()
            scope_lower = scope_type.lower()
            scope_direction = (
                "excluded" if "exclu" in scope_lower
                else "included" if "inclu" in scope_lower
                else "unspecified"
            )
            deal_status = (t.deal_status or "Unknown").strip()
            deal_status_lower = deal_status.lower()
            evidence_status = (
                f"{scope_direction}_in_terminated_deal"
                if "terminat" in deal_status_lower
                else f"{scope_direction}_in_active_deal"
                if deal_status_lower == "active"
                else f"{scope_direction}_in_deal_record"
            )
            territory_list.append({
                "territory": t.territory,
                "scope_type": scope_type or "Unspecified",
                "scope_direction": scope_direction,
                "evidence_status": evidence_status,
                "deal_status": deal_status,
                "participants": t.participants or [],
                "deal_id": t.deal_id,
                "deal_title": t.deal_title,
                "deal_date": t.deal_date,
            })

    return {
        "drug": {"id": drug.id, "name": drug.name, "phase": drug.phase},
        "territories": territory_list,
        "summary": {
            "scope_records": len(territory_list),
            "distinct_territories": len({t["territory"] for t in territory_list}),
            "included_records": sum(1 for t in territory_list if t["scope_direction"] == "included"),
            "excluded_records": sum(1 for t in territory_list if t["scope_direction"] == "excluded"),
            "active_deal_records": sum(1 for t in territory_list if t["deal_status"].lower() == "active"),
        },
        "methodology": (
            "These are Cortellis deal-territory scope records. Active deal status "
            "does not establish current ownership or availability; confirm rights in "
            "the governing agreement and later amendments."
        ),
    }
