"""
Recommendation endpoints — personalized deal suggestions.
"""
from fastapi import APIRouter
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.recommendations import score_deal_relevance, generate_reasons

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["recommendations"])


@router.get("/recommendations")
async def get_recommendations(limit: int = 10):
    """
    Get personalized deal recommendations.
    Currently uses recency + high value as a proxy for relevance.
    Future: use search history and watchlist patterns.
    """
    with get_cortellis_session() as session:
        # Get recent high-value deals as recommendations
        deals = session.execute(text("""
            SELECT
                d.id, d.title, d.agreement_type, d.date_start::text,
                f.total_projected_current_amount as total_value,
                (SELECT c.name FROM deal_companies dc JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal,
                (SELECT c.name FROM deal_companies dc JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner,
                (SELECT i.name FROM deal_indications di JOIN indications i ON i.id = di.indication_id
                 WHERE di.deal_id = d.id LIMIT 1) as indication,
                (SELECT t.name FROM deal_technologies dt JOIN technologies t ON t.id = dt.technology_id
                 WHERE dt.deal_id = d.id LIMIT 1) as modality
            FROM deals d
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE d.date_start >= CURRENT_DATE - INTERVAL '90 days'
              AND f.total_projected_current_amount IS NOT NULL
            ORDER BY f.total_projected_current_amount DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()

        recommendations = []
        for d in deals:
            reasons = []
            if d.total_value and d.total_value > 500:
                reasons.append(f"High-value deal: ${d.total_value:.0f}M")
            if d.indication:
                reasons.append(f"Indication: {d.indication}")
            if d.modality:
                reasons.append(f"Modality: {d.modality}")
            if not reasons:
                reasons.append("Recent notable deal")

            recommendations.append({
                "deal_id": d.id,
                "title": d.title,
                "agreement_type": d.agreement_type,
                "date": d.date_start,
                "value": float(d.total_value) if d.total_value else None,
                "principal": d.principal,
                "partner": d.partner,
                "indication": d.indication,
                "modality": d.modality,
                "reasons": reasons,
            })

    return {"recommendations": recommendations}
