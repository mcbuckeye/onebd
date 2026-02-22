"""
Due Diligence package generation endpoints.
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session
from unified_api.services.dd_generator import build_section, detect_risk_flags, DD_SECTIONS

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["due-diligence"])


class DDGenerateRequest(BaseModel):
    company_id: int
    sections: Optional[List[str]] = None  # If None, generate all


@router.post("/dd/generate")
async def generate_dd_package(req: DDGenerateRequest):
    """
    Generate a comprehensive due diligence package for a company.
    Aggregates data from deals, drugs, partnerships, financials, SEC filings.
    """
    with get_cortellis_session() as session:
        # Get company info
        company = session.execute(text("""
            SELECT id, name, company_type, ticker, hq_location
            FROM companies WHERE id = :id
        """), {"id": req.company_id}).fetchone()

        if not company:
            raise HTTPException(status_code=404, detail="Company not found")

        company_data = {
            "id": company.id,
            "name": company.name,
            "company_type": company.company_type,
            "ticker": company.ticker,
            "hq_location": company.hq_location,
        }

        # Deal history
        deals = session.execute(text("""
            SELECT d.id, d.title, d.agreement_type, d.status, d.date_start::text,
                   f.total_projected_current_amount as total_value,
                   (SELECT c.name FROM deal_companies dc2
                    JOIN companies c ON c.id = dc2.company_id
                    WHERE dc2.deal_id = d.id AND dc2.role != dc.role LIMIT 1) as counterparty
            FROM deal_companies dc
            JOIN deals d ON d.id = dc.deal_id
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE dc.company_id = :company_id
            ORDER BY d.date_start DESC NULLS LAST
            LIMIT 100
        """), {"company_id": req.company_id}).fetchall()

        deal_list = [{
            "id": d.id, "title": d.title, "type": d.agreement_type,
            "status": d.status, "date": d.date_start,
            "value": float(d.total_value) if d.total_value else None,
            "counterparty": d.counterparty,
        } for d in deals]

        # Drug portfolio
        drugs = session.execute(text("""
            SELECT DISTINCT dr.id, dr.name_display as name, dr.phase_highest_now as phase
            FROM deal_companies dc
            JOIN deal_drugs dd ON dd.deal_id = dc.deal_id
            JOIN drugs dr ON dr.id = dd.drug_id
            WHERE dc.company_id = :company_id
            ORDER BY dr.name_display
            LIMIT 50
        """), {"company_id": req.company_id}).fetchall()

        drug_list = [{"id": d.id, "name": d.name, "phase": d.phase} for d in drugs]

        # Top partners
        partners = session.execute(text("""
            SELECT c2.id, c2.name, COUNT(DISTINCT d.id) as deal_count
            FROM deal_companies dc1
            JOIN deals d ON d.id = dc1.deal_id
            JOIN deal_companies dc2 ON dc2.deal_id = d.id AND dc2.company_id != dc1.company_id
            JOIN companies c2 ON c2.id = dc2.company_id
            WHERE dc1.company_id = :company_id
            GROUP BY c2.id, c2.name
            ORDER BY deal_count DESC
            LIMIT 20
        """), {"company_id": req.company_id}).fetchall()

        partner_list = [{"id": p.id, "name": p.name, "deal_count": p.deal_count} for p in partners]

        # Financial summary
        financials = session.execute(text("""
            SELECT
                COUNT(*) as total_deals,
                COUNT(f.total_projected_current_amount) as disclosed_count,
                SUM(f.total_projected_current_amount) as total_value,
                AVG(f.total_projected_current_amount) as avg_value,
                MAX(f.total_projected_current_amount) as max_value,
                COUNT(*) FILTER (WHERE d.status = 'Terminated') as terminated_deals
            FROM deal_companies dc
            JOIN deals d ON d.id = dc.deal_id
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE dc.company_id = :company_id
        """), {"company_id": req.company_id}).fetchone()

        # Check partnership concentration
        concentrated = False
        if partners and financials and financials.total_deals > 5:
            top_partner_pct = partners[0].deal_count / financials.total_deals if financials.total_deals > 0 else 0
            concentrated = top_partner_pct > 0.5

        # Risk flags
        risk_data = {
            "terminated_deals": financials.terminated_deals if financials else 0,
            "total_deals": financials.total_deals if financials else 0,
            "concentrated_partnerships": concentrated,
            "recent_litigation": False,  # Would check SEC filings for litigation
        }
        risk_flags = detect_risk_flags(risk_data)

        # Build sections
        sections_to_build = req.sections or list(DD_SECTIONS.keys())
        section_data = {
            "company_overview": company_data | {"total_deals": financials.total_deals if financials else 0},
            "deal_history": {"deals": deal_list},
            "drug_portfolio": {"drugs": drug_list},
            "partnerships": {"partners": partner_list},
            "financials": {
                "total_deal_value": float(financials.total_value) if financials and financials.total_value else None,
                "avg_deal_value": float(financials.avg_value) if financials and financials.avg_value else None,
                "largest_deal": float(financials.max_value) if financials and financials.max_value else None,
                "disclosed_count": financials.disclosed_count if financials else 0,
            },
            "sec_filings": {"filings": []},  # Would query Edgar DB
            "contracts": {"contracts": []},
            "territory_rights": {"territories": []},
            "comparable_transactions": {"comps": []},
            "risk_assessment": {"risk_flags": risk_flags},
        }

        built_sections = []
        for section_type in sections_to_build:
            data = section_data.get(section_type, {})
            built_sections.append(build_section(section_type, data))

    return {
        "company": company_data,
        "sections": built_sections,
        "risk_flags": risk_flags,
        "metadata": {
            "total_deals_analyzed": financials.total_deals if financials else 0,
            "financial_disclosure_rate": f"{(financials.disclosed_count / financials.total_deals * 100):.0f}%" if financials and financials.total_deals > 0 else "N/A",
        },
    }
