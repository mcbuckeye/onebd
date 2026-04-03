"""
Executive dashboard endpoint.
Returns pre-aggregated data for the landing page.
"""
from fastapi import APIRouter
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.cache import cache_get, cache_set, cache_key

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/executive")
async def get_executive_dashboard():
    """
    Pre-aggregated executive dashboard data.
    Cached for 30 minutes.
    """
    key = cache_key("dashboard_executive")
    cached = cache_get(key)
    if cached:
        return cached

    with get_cortellis_session() as session:
        # Deal count last 30 days vs previous 30 days
        pulse = session.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE date_start >= CURRENT_DATE - INTERVAL '30 days') as count_30d,
                COUNT(*) FILTER (WHERE date_start >= CURRENT_DATE - INTERVAL '60 days'
                                  AND date_start < CURRENT_DATE - INTERVAL '30 days') as count_prev_30d
            FROM deals
            WHERE date_start IS NOT NULL
        """)).fetchone()

        # Average deal value last 30 days (disclosed only)
        avg_val = session.execute(text("""
            SELECT AVG(f.total_projected_current_amount) as avg_value,
                   COUNT(*) as disclosed_count
            FROM deals d
            JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE d.date_start >= CURRENT_DATE - INTERVAL '30 days'
              AND f.total_projected_current_amount IS NOT NULL
        """)).fetchone()

        # Top therapy areas (last 90 days)
        therapy_areas = session.execute(text("""
            SELECT ta.name, COUNT(*) as count
            FROM deals d
            JOIN therapy_areas ta ON ta.id = d.therapy_area_id
            WHERE d.date_start >= CURRENT_DATE - INTERVAL '90 days'
              AND ta.name IS NOT NULL
            GROUP BY ta.name
            ORDER BY count DESC
            LIMIT 5
        """)).fetchall()

        # Notable deals (highest value, last 60 days)
        notable = session.execute(text("""
            SELECT
                d.id, d.title, d.agreement_type, d.status,
                d.date_start::text,
                f.total_projected_current_amount as total_value,
                (SELECT c.name FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal,
                (SELECT c.id FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal_id,
                (SELECT c.name FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner,
                (SELECT c.id FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner_id
            FROM deals d
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE d.date_start >= CURRENT_DATE - INTERVAL '60 days'
            ORDER BY f.total_projected_current_amount DESC NULLS LAST
            LIMIT 10
        """)).fetchall()

        # Deal count by month (last 12 months) for sparkline
        monthly_trend = session.execute(text("""
            SELECT
                DATE_TRUNC('month', date_start)::date::text as month,
                COUNT(*) as count
            FROM deals
            WHERE date_start >= CURRENT_DATE - INTERVAL '12 months'
              AND date_start IS NOT NULL
            GROUP BY DATE_TRUNC('month', date_start)
            ORDER BY month
        """)).fetchall()

    result = {
        "market_pulse": {
            "deal_count_30d": pulse.count_30d if pulse else 0,
            "deal_count_prev_30d": pulse.count_prev_30d if pulse else 0,
            "avg_value_30d": float(avg_val.avg_value) if avg_val and avg_val.avg_value else None,
            "disclosed_count_30d": avg_val.disclosed_count if avg_val else 0,
            "top_therapy_areas": [{"name": r.name, "count": r.count} for r in therapy_areas],
            "monthly_trend": [{"month": r.month, "count": r.count} for r in monthly_trend],
        },
        "notable_deals": [
            {
                "id": r.id,
                "title": r.title,
                "agreement_type": r.agreement_type,
                "status": r.status,
                "date_start": r.date_start,
                "total_value": float(r.total_value) if r.total_value else None,
                "principal_company": r.principal,
                "partner_company": r.partner,
                "principal_company_id": r.principal_id,
                "partner_company_id": r.partner_id,
            }
            for r in notable
        ],
    }

    cache_set(key, result, ttl=1800)  # 30 min
    return result
