"""
Briefing generation and management endpoints.
"""
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.briefing_generator import build_market_summary, build_competitor_summary, build_notable_deals

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["briefings"])


class BriefingRequest(BaseModel):
    topic: str
    period_days: int = 30


@router.post("/briefings/generate")
async def generate_briefing(req: BriefingRequest):
    """Generate an on-demand briefing on a topic."""
    with get_cortellis_session() as session:
        # Market stats
        market = session.execute(text("""
            SELECT COUNT(*) as deal_count
            FROM deals
            WHERE date_start >= CURRENT_DATE - make_interval(days => :days)
        """), {"days": req.period_days}).fetchone()

        # Top therapy area
        top_ta = session.execute(text("""
            SELECT ta.name, COUNT(*) as cnt
            FROM deals d
            JOIN therapy_areas ta ON ta.id = d.therapy_area_id
            WHERE d.date_start >= CURRENT_DATE - make_interval(days => :days)
              AND ta.name IS NOT NULL
            GROUP BY ta.name ORDER BY cnt DESC LIMIT 1
        """), {"days": req.period_days}).fetchone()

        # Notable deals (filtered by topic if it looks like a therapy area/company)
        notable_query = """
            SELECT d.id, d.title, d.agreement_type, d.date_start::text,
                   f.total_projected_current_amount as total_value,
                   (SELECT c.name FROM deal_companies dc JOIN companies c ON c.id = dc.company_id
                    WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal,
                   (SELECT c.name FROM deal_companies dc JOIN companies c ON c.id = dc.company_id
                    WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner
            FROM deals d
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE d.date_start >= CURRENT_DATE - make_interval(days => :days)
        """
        params: dict = {"days": req.period_days}

        if req.topic:
            notable_query += """
                AND (d.title ILIKE :topic_search
                     OR d.id IN (SELECT dc.deal_id FROM deal_companies dc
                                 JOIN companies c ON c.id = dc.company_id
                                 WHERE c.name ILIKE :topic_search)
                     OR d.id IN (SELECT di.deal_id FROM deal_indications di
                                 JOIN indications i ON i.id = di.indication_id
                                 WHERE i.name ILIKE :topic_search)
                     OR d.id IN (SELECT dt2.deal_id FROM deal_technologies dt2
                                 JOIN technologies t ON t.id = dt2.technology_id
                                 WHERE t.name ILIKE :topic_search))
            """
            params["topic_search"] = f"%{req.topic}%"

        notable_query += " ORDER BY f.total_projected_current_amount DESC NULLS LAST LIMIT 10"

        notable = session.execute(text(notable_query), params).fetchall()

        notable_list = [{
            "id": d.id, "title": d.title, "type": d.agreement_type,
            "date": d.date_start,
            "value": float(d.total_value) if d.total_value else None,
            "principal": d.principal, "partner": d.partner,
        } for d in notable]

    sections = [
        build_market_summary({
            "deals_30d": market.deal_count if market else 0,
            "top_therapy": top_ta.name if top_ta else None,
        }),
        build_notable_deals(notable_list),
    ]

    return {
        "title": f"Intelligence Briefing: {req.topic}",
        "topic": req.topic,
        "period_days": req.period_days,
        "sections": sections,
        "generated_at": "now",
    }


@router.get("/briefings")
async def list_briefings():
    """List generated briefings (placeholder for persistence)."""
    return []
