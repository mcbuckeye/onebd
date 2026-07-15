"""
Briefing generation and management endpoints.
"""
from datetime import datetime, timezone
from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.briefing_generator import build_market_summary, build_notable_deals

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["briefings"])


class BriefingRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)
    period_days: int = Field(default=30, ge=1, le=3650)

    @field_validator("topic")
    @classmethod
    def normalize_topic(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("topic cannot be blank")
        return cleaned


def _search_topic(topic: str) -> str:
    """Remove UI nouns that otherwise turn useful topics into impossible phrases."""
    generic_suffixes = (" deals", " deal", " activity", " market")
    cleaned = topic.strip()
    lowered = cleaned.lower()
    for suffix in generic_suffixes:
        if lowered.endswith(suffix) and len(cleaned) > len(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
            break
    return cleaned


TOPIC_FILTER_SQL = """
    (d.title ILIKE :topic_search
     OR d.summary ILIKE :topic_search
     OR EXISTS (SELECT 1 FROM deal_companies dc
                JOIN companies c ON c.id = dc.company_id
                WHERE dc.deal_id = d.id AND c.name ILIKE :topic_search)
     OR EXISTS (SELECT 1 FROM deal_indications di
                JOIN indications i ON i.id = di.indication_id
                WHERE di.deal_id = d.id AND i.name ILIKE :topic_search)
     OR EXISTS (SELECT 1 FROM deal_technologies dt2
                JOIN technologies t ON t.id = dt2.technology_id
                WHERE dt2.deal_id = d.id AND t.name ILIKE :topic_search)
     OR EXISTS (SELECT 1 FROM deal_drugs dd
                JOIN drugs drug ON drug.id = dd.drug_id
                WHERE dd.deal_id = d.id AND drug.name_display ILIKE :topic_search)
     OR EXISTS (SELECT 1 FROM therapy_areas topic_ta
                WHERE topic_ta.id = d.therapy_area_id
                  AND topic_ta.name ILIKE :topic_search))
"""


@router.post("/briefings/generate")
async def generate_briefing(req: BriefingRequest):
    """Generate an on-demand briefing on a topic."""
    topic_search = _search_topic(req.topic)
    params: dict = {
        "days": req.period_days,
        "topic_search": f"%{topic_search}%",
    }
    with get_cortellis_session() as session:
        # Topic-scoped market stats
        market = session.execute(text(f"""
            SELECT COUNT(DISTINCT d.id) as deal_count
            FROM deals d
            WHERE d.date_start >= CURRENT_DATE - make_interval(days => :days)
              AND {TOPIC_FILTER_SQL}
        """), params).fetchone()

        # Top therapy area
        top_ta = session.execute(text(f"""
            SELECT ta.name, COUNT(*) as cnt
            FROM deals d
            JOIN therapy_areas ta ON ta.id = d.therapy_area_id
            WHERE d.date_start >= CURRENT_DATE - make_interval(days => :days)
              AND ta.name IS NOT NULL
              AND {TOPIC_FILTER_SQL}
            GROUP BY ta.name ORDER BY cnt DESC LIMIT 1
        """), params).fetchone()

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
              AND f.total_projected_current_currency = 'USD'
              AND f.total_projected_current_unit = 'Million'
            WHERE d.date_start >= CURRENT_DATE - make_interval(days => :days)
        """
        notable_query += f" AND {TOPIC_FILTER_SQL}"

        notable_query += " ORDER BY f.total_projected_current_amount DESC NULLS LAST LIMIT 10"

        notable = session.execute(text(notable_query), params).fetchall()

        notable_list = [{
            "id": d.id, "title": d.title, "type": d.agreement_type,
            "date": d.date_start,
            "value": float(d.total_value) if d.total_value is not None else None,
            "principal": d.principal, "partner": d.partner,
        } for d in notable]

    sections = [
        build_market_summary({
            "matching_deals": market.deal_count if market else 0,
            "top_therapy": top_ta.name if top_ta else None,
        }),
        build_notable_deals(notable_list),
    ]

    return {
        "title": f"Intelligence Briefing: {req.topic}",
        "topic": req.topic,
        "period_days": req.period_days,
        "sections": sections,
        "search_term": topic_search,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": (
            "Counts and notable deals are restricted to the requested time window "
            "and records matching the topic in deal, company, indication, technology, "
            "asset, therapy-area, or summary fields."
        ),
    }


@router.get("/briefings")
async def list_briefings():
    """Briefings are currently generated on demand and are not persisted."""
    return {"briefings": [], "persistence_enabled": False}
