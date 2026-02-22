"""
Due Diligence package generator.
Orchestrates data from multiple sources into a comprehensive DD report.
"""
from typing import Dict, Any, List, Optional
import structlog

logger = structlog.get_logger(__name__)

DD_SECTIONS = {
    "company_overview": "Company Overview",
    "deal_history": "Deal History",
    "drug_portfolio": "Drug / Asset Portfolio",
    "partnerships": "Partnership Network",
    "financials": "Financial Summary",
    "sec_filings": "SEC Filings",
    "contracts": "Key Contracts",
    "territory_rights": "Territory Rights",
    "comparable_transactions": "Comparable Transactions",
    "risk_assessment": "Risk Assessment",
}


def build_section(section_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Build a single DD section from data."""
    title = DD_SECTIONS.get(section_type, section_type.replace("_", " ").title())

    if section_type == "company_overview":
        return {
            "type": section_type,
            "title": title,
            "content": {
                "name": data.get("name"),
                "company_type": data.get("company_type"),
                "ticker": data.get("ticker"),
                "hq_location": data.get("hq_location"),
                "total_deals": data.get("total_deals", 0),
            },
        }
    elif section_type == "deal_history":
        return {
            "type": section_type,
            "title": title,
            "content": data.get("deals", []),
        }
    elif section_type == "drug_portfolio":
        return {
            "type": section_type,
            "title": title,
            "content": data.get("drugs", []),
        }
    elif section_type == "partnerships":
        return {
            "type": section_type,
            "title": title,
            "content": data.get("partners", []),
        }
    elif section_type == "financials":
        return {
            "type": section_type,
            "title": title,
            "content": {
                "total_deal_value": data.get("total_deal_value"),
                "avg_deal_value": data.get("avg_deal_value"),
                "largest_deal": data.get("largest_deal"),
                "deal_count_with_financials": data.get("disclosed_count", 0),
            },
        }
    elif section_type == "sec_filings":
        return {
            "type": section_type,
            "title": title,
            "content": data.get("filings", []),
        }
    elif section_type == "contracts":
        return {
            "type": section_type,
            "title": title,
            "content": data.get("contracts", []),
        }
    elif section_type == "territory_rights":
        return {
            "type": section_type,
            "title": title,
            "content": data.get("territories", []),
        }
    elif section_type == "comparable_transactions":
        return {
            "type": section_type,
            "title": title,
            "content": data.get("comps", []),
        }
    elif section_type == "risk_assessment":
        return {
            "type": section_type,
            "title": title,
            "content": data.get("risk_flags", []),
        }
    else:
        return {"type": section_type, "title": title, "content": None}


def detect_risk_flags(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Detect risk flags from company/deal data."""
    flags = []

    terminated = data.get("terminated_deals", 0)
    total = data.get("total_deals", 0)

    if total > 0 and terminated / total > 0.3:
        flags.append({
            "flag": f"High termination rate: {terminated}/{total} deals terminated ({(terminated/total*100):.0f}%)",
            "severity": "high",
            "category": "deal_stability",
        })

    if data.get("concentrated_partnerships"):
        flags.append({
            "flag": "Partnership concentration: >50% of deals with a single partner",
            "severity": "medium",
            "category": "dependency",
        })

    if data.get("recent_litigation"):
        flags.append({
            "flag": "Recent litigation-related SEC filings detected",
            "severity": "high",
            "category": "legal",
        })

    if total < 3:
        flags.append({
            "flag": f"Limited deal history: only {total} deals on record",
            "severity": "medium",
            "category": "track_record",
        })

    if total > 0 and terminated == 0:
        flags.append({
            "flag": "No terminated deals on record (positive indicator)",
            "severity": "low",
            "category": "deal_stability",
        })

    return flags
