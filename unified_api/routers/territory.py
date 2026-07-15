"""
Territory rights endpoints.
"""
from fastapi import APIRouter, HTTPException
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["territory"])


@router.get("/territory/{drug_id}/map")
async def get_territory_map(drug_id: int):
    """
    Get territory rights map for a drug/asset.
    Returns territories with commitment status.
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
                d.id as deal_id,
                d.title as deal_title,
                d.status as deal_status,
                d.date_start::text as deal_date,
                (SELECT c.name FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as rights_holder
            FROM deal_drugs dd
            JOIN deals d ON d.id = dd.deal_id
            JOIN deal_territories dt ON dt.deal_id = d.id
            JOIN territories t ON t.id = dt.territory_id
            WHERE dd.drug_id = :drug_id
            ORDER BY t.name
        """), {"drug_id": drug_id}).fetchall()

        territory_list = []
        for t in territories:
            status = "committed" if t.deal_status == "Active" else "terminated" if t.deal_status == "Terminated" else "unknown"
            territory_list.append({
                "territory": t.territory,
                "status": status,
                "rights_holder": t.rights_holder,
                "deal_id": t.deal_id,
                "deal_title": t.deal_title,
                "deal_date": t.deal_date,
            })

    return {
        "drug": {"id": drug.id, "name": drug.name, "phase": drug.phase},
        "territories": territory_list,
        "summary": {
            "total_territories": len(territory_list),
            "committed": sum(1 for t in territory_list if t["status"] == "committed"),
            "terminated": sum(1 for t in territory_list if t["status"] == "terminated"),
        },
    }
