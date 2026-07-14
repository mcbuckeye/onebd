"""Source-backed due-diligence package generation endpoints."""

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
import structlog

from unified_api.services.contract_financial_clauses import (
    CONTRACT_CLAUSE_PARSER_VERSION,
)
from unified_api.services.database import get_cortellis_session, get_edgar_session
from unified_api.services.dd_generator import DD_SECTIONS, build_section, detect_risk_flags


logger = structlog.get_logger(__name__)
router = APIRouter(tags=["due-diligence"])


class DDGenerateRequest(BaseModel):
    company_id: int = Field(gt=0)
    sections: Optional[List[str]] = None


def _optional_float(value):
    return float(value) if value is not None else None


def _load_sec_filings(company: dict, xref: dict | None) -> dict:
    """Load recent filings only through a durable xref or exact CIK fallback."""
    edgar_company_id = xref.get("edgar_company_id") if xref else None
    cik = (xref or {}).get("cik") or company.get("cik")
    identity_method = (xref or {}).get("match_method")
    identity_confidence = (xref or {}).get("match_confidence")
    manually_verified = bool((xref or {}).get("manually_verified"))

    with get_edgar_session() as session:
        if edgar_company_id is None and cik:
            exact = session.execute(text("""
                SELECT id, cik FROM companies
                WHERE LTRIM(cik, '0') = LTRIM(:cik, '0')
                ORDER BY id LIMIT 1
            """), {"cik": cik}).mappings().first()
            if exact:
                edgar_company_id = int(exact["id"])
                cik = exact["cik"]
                identity_method = "exact_cik_fallback"
                identity_confidence = 1.0

        if edgar_company_id is None:
            return {
                "filings": [],
                "status": "unmapped",
                "source": "SEC EDGAR",
                "coverage": {
                    "edgar_company_id": None,
                    "cik": cik,
                    "identity_method": identity_method,
                    "identity_confidence": identity_confidence,
                    "manually_verified": manually_verified,
                },
                "methodology": (
                    "No filing was returned because this Cortellis company lacks "
                    "a durable EDGAR company match or exact CIK match."
                ),
            }

        rows = session.execute(text("""
            SELECT document.id, document.accession_no,
                   COALESCE(document.subtype, document.doc_type) AS doc_type,
                   document.title, raw.filing_date::text,
                   document.published_at::text, raw.url AS source_url,
                   document.parse_ok,
                   (SELECT COUNT(*) FROM chunks chunk
                    WHERE chunk.document_id=document.id) AS chunk_count,
                   COUNT(*) OVER () AS total_filings
            FROM documents document
            JOIN raw_documents raw ON raw.id=document.raw_document_id
            WHERE raw.company_id=:company_id
            ORDER BY raw.filing_date DESC NULLS LAST, document.id DESC
            LIMIT 25
        """), {"company_id": edgar_company_id}).mappings().all()

    filings = [
        {
            "id": int(row["id"]),
            "accession_no": row["accession_no"],
            "doc_type": row["doc_type"],
            "title": row["title"],
            "filing_date": row["filing_date"],
            "published_at": row["published_at"],
            "source_url": row["source_url"],
            "parse_ok": row["parse_ok"],
            "chunk_count": int(row["chunk_count"] or 0),
            "source": "SEC EDGAR",
        }
        for row in rows
    ]
    return {
        "filings": filings,
        "status": "available" if filings else "no_data",
        "source": "SEC EDGAR",
        "coverage": {
            "edgar_company_id": int(edgar_company_id),
            "cik": cik,
            "identity_method": identity_method,
            "identity_confidence": identity_confidence,
            "manually_verified": manually_verified,
            "total_filings": int(rows[0]["total_filings"]) if rows else 0,
            "returned_filings": len(filings),
        },
        "methodology": (
            "The 25 most recent filings for the source-confirmed EDGAR company "
            "identity are returned with canonical SEC URLs and parse coverage."
        ),
    }


@router.post("/dd/generate")
async def generate_dd_package(req: DDGenerateRequest):
    """Generate a source-attributed multi-source company DD package."""
    unknown_sections = sorted(set(req.sections or []) - set(DD_SECTIONS))
    if unknown_sections:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown DD sections: {', '.join(unknown_sections)}",
        )
    sections_to_build = req.sections or list(DD_SECTIONS)

    with get_cortellis_session() as session:
        company_row = session.execute(text("""
            SELECT id, name, company_type, ticker, hq_location, cik
            FROM companies WHERE id=:id
        """), {"id": req.company_id}).mappings().first()
        if not company_row:
            raise HTTPException(status_code=404, detail="Company not found")
        company_data = dict(company_row)

        financials = session.execute(text("""
            WITH company_deals AS (
                SELECT DISTINCT deal_id
                FROM deal_companies WHERE company_id=:company_id
            )
            SELECT COUNT(*) AS total_deals,
                   COUNT(*) FILTER (
                       WHERE finance.total_projected_current_amount IS NOT NULL
                         AND finance.total_projected_current_currency='USD'
                         AND finance.total_projected_current_unit='Million'
                         AND finance.total_projected_current_disclosure_status='Known'
                   ) AS disclosed_count,
                   SUM(finance.total_projected_current_amount) FILTER (
                       WHERE finance.total_projected_current_currency='USD'
                         AND finance.total_projected_current_unit='Million'
                         AND finance.total_projected_current_disclosure_status='Known'
                   ) AS total_value,
                   AVG(finance.total_projected_current_amount) FILTER (
                       WHERE finance.total_projected_current_currency='USD'
                         AND finance.total_projected_current_unit='Million'
                         AND finance.total_projected_current_disclosure_status='Known'
                   ) AS avg_value,
                   MAX(finance.total_projected_current_amount) FILTER (
                       WHERE finance.total_projected_current_currency='USD'
                         AND finance.total_projected_current_unit='Million'
                         AND finance.total_projected_current_disclosure_status='Known'
                   ) AS max_value,
                   COUNT(*) FILTER (WHERE deal.status='Terminated')
                       AS terminated_deals
            FROM company_deals company_deal
            JOIN deals deal ON deal.id=company_deal.deal_id
            LEFT JOIN deal_finance_summary finance ON finance.deal_id=deal.id
        """), {"company_id": req.company_id}).mappings().one()

        deal_rows = []
        if "deal_history" in sections_to_build:
            deal_rows = session.execute(text("""
                SELECT deal.id, deal.title, deal.agreement_type, deal.status,
                       deal.date_start::text,
                       finance.total_projected_current_amount AS total_value,
                       finance.total_projected_current_currency AS currency,
                       finance.total_projected_current_unit AS unit,
                       finance.total_projected_current_disclosure_status
                           AS disclosure_status,
                       (SELECT company.name FROM deal_companies other_link
                        JOIN companies company ON company.id=other_link.company_id
                        WHERE other_link.deal_id=deal.id
                          AND other_link.company_id<>:company_id
                        ORDER BY company.name LIMIT 1) AS counterparty
                FROM deal_companies company_link
                JOIN deals deal ON deal.id=company_link.deal_id
                LEFT JOIN deal_finance_summary finance ON finance.deal_id=deal.id
                WHERE company_link.company_id=:company_id
                GROUP BY deal.id, finance.deal_id
                ORDER BY deal.date_start DESC NULLS LAST, deal.id DESC
                LIMIT 100
            """), {"company_id": req.company_id}).mappings().all()
        deal_list = [
            {
                "id": int(row["id"]),
                "title": row["title"],
                "type": row["agreement_type"],
                "status": row["status"],
                "date": row["date_start"],
                "value": _optional_float(row["total_value"]),
                "currency": row["currency"],
                "unit": row["unit"],
                "disclosure_status": row["disclosure_status"],
                "counterparty": row["counterparty"],
                "source": "Cortellis Deals",
            }
            for row in deal_rows
        ]

        drug_rows = []
        if "drug_portfolio" in sections_to_build:
            drug_rows = session.execute(text("""
                SELECT DISTINCT drug.id, drug.name_display AS name,
                       drug.phase_highest_now AS phase
                FROM deal_companies company_link
                JOIN deal_drugs deal_drug ON deal_drug.deal_id=company_link.deal_id
                JOIN drugs drug ON drug.id=deal_drug.drug_id
                WHERE company_link.company_id=:company_id
                ORDER BY drug.name_display
                LIMIT 50
            """), {"company_id": req.company_id}).mappings().all()
        drug_list = [
            {"id": int(row["id"]), "name": row["name"], "phase": row["phase"]}
            for row in drug_rows
        ]

        partner_rows = session.execute(text("""
            SELECT company.id, company.name,
                   COUNT(DISTINCT deal.id) AS deal_count
            FROM deal_companies target_link
            JOIN deals deal ON deal.id=target_link.deal_id
            JOIN deal_companies partner_link
              ON partner_link.deal_id=deal.id
             AND partner_link.company_id<>target_link.company_id
            JOIN companies company ON company.id=partner_link.company_id
            WHERE target_link.company_id=:company_id
            GROUP BY company.id, company.name
            ORDER BY deal_count DESC, company.name
            LIMIT 20
        """), {"company_id": req.company_id}).mappings().all()
        partner_list = [
            {
                "id": int(row["id"]),
                "name": row["name"],
                "deal_count": int(row["deal_count"]),
            }
            for row in partner_rows
        ]

        xref_row = session.execute(text("""
            SELECT edgar_company_id, cik, match_method, match_confidence,
                   manually_verified
            FROM company_xref WHERE cortellis_id=:company_id
            ORDER BY manually_verified DESC, match_confidence DESC NULLS LAST
            LIMIT 1
        """), {"company_id": req.company_id}).mappings().first()
        xref = dict(xref_row) if xref_row else None

        contract_rows = []
        if "contracts" in sections_to_build:
            contract_rows = session.execute(text("""
                SELECT contract.id AS contract_id, contract.deal_id,
                       deal.title AS deal_title, contract.contract_types,
                       contract.date_contract::text, contract.date_filing::text,
                       contract.has_pdf, contract.has_text, contract.is_redacted,
                       content.id AS content_id, content.word_count,
                       COUNT(*) OVER () AS total_contracts,
                       (SELECT COUNT(*)
                        FROM contract_financial_clauses clause
                        WHERE clause.contract_id=content.id
                          AND clause.parser_version=:parser_version
                          AND clause.review_status<>'rejected')
                           AS financial_clause_count,
                       COALESCE((
                           SELECT JSONB_AGG(JSONB_BUILD_OBJECT(
                               'id', candidate.id,
                               'clause_type', candidate.clause_type,
                               'rate_min_pct', candidate.rate_min_pct,
                               'rate_max_pct', candidate.rate_max_pct,
                               'amount_min_millions', candidate.amount_min_millions,
                               'amount_max_millions', candidate.amount_max_millions,
                               'currency', candidate.currency,
                               'is_tiered', candidate.is_tiered,
                               'confidence', candidate.confidence,
                               'review_status', candidate.review_status,
                               'source_excerpt', LEFT(candidate.source_text, 500),
                               'source_hash', candidate.source_hash,
                               'parser_version', candidate.parser_version
                           ) ORDER BY
                               CASE candidate.review_status
                                   WHEN 'accepted' THEN 0 ELSE 1 END,
                               candidate.confidence DESC, candidate.id)
                           FROM (
                               SELECT clause.*
                               FROM contract_financial_clauses clause
                               WHERE clause.contract_id=content.id
                                 AND clause.parser_version=:parser_version
                                 AND clause.review_status<>'rejected'
                               ORDER BY
                                   CASE clause.review_status
                                       WHEN 'accepted' THEN 0 ELSE 1 END,
                                   clause.confidence DESC, clause.id
                               LIMIT 5
                           ) candidate
                       ), '[]'::JSONB) AS key_financial_clauses
                FROM deal_contracts contract
                JOIN deals deal ON deal.id=contract.deal_id
                JOIN (
                    SELECT DISTINCT deal_id FROM deal_companies
                    WHERE company_id=:company_id
                ) company_link ON company_link.deal_id=contract.deal_id
                LEFT JOIN contract_content content
                  ON content.contract_id=contract.id
                ORDER BY financial_clause_count DESC,
                         (content.id IS NOT NULL) DESC,
                         COALESCE(contract.date_contract, contract.date_filing)
                             DESC NULLS LAST,
                         contract.id DESC
                LIMIT 25
            """), {
                "company_id": req.company_id,
                "parser_version": CONTRACT_CLAUSE_PARSER_VERSION,
            }).mappings().all()
        contracts = [
            {
                "contract_id": int(row["contract_id"]),
                "deal_id": int(row["deal_id"]),
                "deal_title": row["deal_title"],
                "contract_types": row["contract_types"],
                "date_contract": row["date_contract"],
                "date_filing": row["date_filing"],
                "has_pdf": bool(row["has_pdf"]),
                "has_text": bool(row["has_text"]),
                "is_redacted": bool(row["is_redacted"]),
                "content_id": int(row["content_id"]) if row["content_id"] else None,
                "word_count": int(row["word_count"] or 0),
                "financial_clause_count": int(
                    row["financial_clause_count"] or 0
                ),
                "key_financial_clauses": row["key_financial_clauses"] or [],
                "source": "Cortellis contract record",
            }
            for row in contract_rows
        ]

        territory_rows = []
        if "territory_rights" in sections_to_build:
            territory_rows = session.execute(text("""
                SELECT territory.id AS territory_id,
                       territory.name AS territory,
                       deal_territory.territory_type AS scope_type,
                       deal.id AS deal_id, deal.title AS deal_title,
                       deal.status AS deal_status, deal.date_start::text,
                       company_link.role AS company_role,
                       ARRAY_AGG(DISTINCT drug.name_display)
                           FILTER (WHERE drug.id IS NOT NULL) AS assets,
                       COUNT(*) OVER () AS total_scope_records
                FROM deal_companies company_link
                JOIN deals deal ON deal.id=company_link.deal_id
                JOIN deal_territories deal_territory
                  ON deal_territory.deal_id=deal.id
                JOIN territories territory
                  ON territory.id=deal_territory.territory_id
                LEFT JOIN deal_drugs deal_drug ON deal_drug.deal_id=deal.id
                LEFT JOIN drugs drug ON drug.id=deal_drug.drug_id
                WHERE company_link.company_id=:company_id
                GROUP BY territory.id, territory.name,
                         deal_territory.territory_type, deal.id,
                         company_link.role
                ORDER BY deal.date_start DESC NULLS LAST, deal.id DESC,
                         territory.name
                LIMIT 100
            """), {"company_id": req.company_id}).mappings().all()
        territories = [
            {
                "territory_id": row["territory_id"],
                "territory": row["territory"],
                "scope_type": row["scope_type"],
                "deal_id": int(row["deal_id"]),
                "deal_title": row["deal_title"],
                "deal_status": row["deal_status"],
                "date_start": row["date_start"],
                "company_role": row["company_role"],
                "assets": row["assets"] or [],
                "source": "Cortellis deal territory scope",
            }
            for row in territory_rows
        ]

        comp_rows = []
        if "comparable_transactions" in sections_to_build:
            comp_rows = session.execute(text("""
                WITH target_deals AS MATERIALIZED (
                    SELECT DISTINCT deal.*
                    FROM deal_companies company_link
                    JOIN deals deal ON deal.id=company_link.deal_id
                    WHERE company_link.company_id=:company_id
                ), profile AS (
                    SELECT
                      (SELECT therapy_area_id FROM target_deals
                       WHERE therapy_area_id IS NOT NULL
                       GROUP BY therapy_area_id
                       ORDER BY COUNT(*) DESC, therapy_area_id LIMIT 1)
                         AS therapy_area_id,
                      (SELECT agreement_type FROM target_deals
                       WHERE agreement_type IS NOT NULL
                       GROUP BY agreement_type
                       ORDER BY COUNT(*) DESC, agreement_type LIMIT 1)
                         AS agreement_type,
                      (SELECT phase_highest_start FROM target_deals
                       WHERE phase_highest_start IS NOT NULL
                       GROUP BY phase_highest_start
                       ORDER BY COUNT(*) DESC, phase_highest_start LIMIT 1)
                         AS phase
                ), scored AS (
                    SELECT deal.id, deal.title, deal.agreement_type,
                           deal.status, deal.date_start::text,
                           deal.phase_highest_start,
                           therapy.name AS therapy_area,
                           finance.total_projected_current_amount AS total_value,
                           finance.total_projected_current_currency AS currency,
                           finance.total_projected_current_unit AS unit,
                           finance.total_projected_current_disclosure_status
                               AS disclosure_status,
                           (CASE WHEN profile.agreement_type IS NOT NULL
                                      AND deal.agreement_type=profile.agreement_type
                                  THEN 4 ELSE 0 END
                            + CASE WHEN profile.therapy_area_id IS NOT NULL
                                      AND deal.therapy_area_id=profile.therapy_area_id
                                  THEN 3 ELSE 0 END
                            + CASE WHEN profile.phase IS NOT NULL
                                      AND deal.phase_highest_start=profile.phase
                                  THEN 2 ELSE 0 END) AS similarity_score,
                           ARRAY_REMOVE(ARRAY[
                             CASE WHEN profile.agreement_type IS NOT NULL
                                        AND deal.agreement_type=profile.agreement_type
                                  THEN 'dominant agreement type' END,
                             CASE WHEN profile.therapy_area_id IS NOT NULL
                                        AND deal.therapy_area_id=profile.therapy_area_id
                                  THEN 'dominant therapy area' END,
                             CASE WHEN profile.phase IS NOT NULL
                                        AND deal.phase_highest_start=profile.phase
                                  THEN 'dominant phase at signing' END
                           ], NULL) AS match_reasons,
                           (SELECT company.name FROM deal_companies link
                            JOIN companies company ON company.id=link.company_id
                            WHERE link.deal_id=deal.id AND link.role='Principal'
                            ORDER BY company.name LIMIT 1) AS principal,
                           (SELECT company.name FROM deal_companies link
                            JOIN companies company ON company.id=link.company_id
                            WHERE link.deal_id=deal.id AND link.role='Partner'
                            ORDER BY company.name LIMIT 1) AS partner
                    FROM deals deal CROSS JOIN profile
                    LEFT JOIN therapy_areas therapy
                      ON therapy.id=deal.therapy_area_id
                    LEFT JOIN deal_finance_summary finance
                      ON finance.deal_id=deal.id
                    WHERE NOT EXISTS (
                        SELECT 1 FROM deal_companies target_link
                        WHERE target_link.deal_id=deal.id
                          AND target_link.company_id=:company_id
                    )
                )
                SELECT *, COUNT(*) OVER () AS total_comparable_candidates
                FROM scored WHERE similarity_score>0
                ORDER BY similarity_score DESC,
                         (total_value IS NOT NULL) DESC,
                         date_start DESC NULLS LAST, id DESC
                LIMIT 20
            """), {"company_id": req.company_id}).mappings().all()
        comps = [
            {
                "id": int(row["id"]),
                "title": row["title"],
                "agreement_type": row["agreement_type"],
                "status": row["status"],
                "date_start": row["date_start"],
                "phase_at_signing": row["phase_highest_start"],
                "therapy_area": row["therapy_area"],
                "total_value": _optional_float(row["total_value"]),
                "currency": row["currency"],
                "unit": row["unit"],
                "disclosure_status": row["disclosure_status"],
                "similarity_score": int(row["similarity_score"]),
                "match_reasons": row["match_reasons"] or [],
                "principal": row["principal"],
                "partner": row["partner"],
                "source": "Cortellis Deals",
            }
            for row in comp_rows
        ]

    sec_data = (
        _load_sec_filings(company_data, xref)
        if "sec_filings" in sections_to_build
        else {"filings": [], "status": "not_requested"}
    )

    total_deals = int(financials["total_deals"] or 0)
    disclosed_count = int(financials["disclosed_count"] or 0)
    concentrated = bool(
        partner_list
        and total_deals > 5
        and int(partner_list[0]["deal_count"]) / total_deals > 0.5
    )
    risk_flags = detect_risk_flags({
        "terminated_deals": int(financials["terminated_deals"] or 0),
        "total_deals": total_deals,
        "concentrated_partnerships": concentrated,
        "recent_litigation": False,
    })

    section_data = {
        "company_overview": {
            **company_data,
            "total_deals": total_deals,
            "source": "Cortellis Deals",
        },
        "deal_history": {
            "deals": deal_list,
            "source": "Cortellis Deals",
            "coverage": {"returned_deals": len(deal_list), "total_deals": total_deals},
        },
        "drug_portfolio": {
            "drugs": drug_list,
            "source": "Cortellis deal-embedded assets",
        },
        "partnerships": {
            "partners": partner_list,
            "source": "Cortellis deal company roles",
        },
        "financials": {
            "total_deal_value": _optional_float(financials["total_value"]),
            "avg_deal_value": _optional_float(financials["avg_value"]),
            "largest_deal": _optional_float(financials["max_value"]),
            "disclosed_count": disclosed_count,
            "source": "Cortellis disclosed current projected totals",
            "methodology": (
                "Only Known USD amounts reported in millions are aggregated; "
                "different currencies and units are not summed."
            ),
        },
        "sec_filings": sec_data,
        "contracts": {
            "contracts": contracts,
            "source": (
                "Cortellis contract metadata/text and deterministic financial "
                f"clause parser v{CONTRACT_CLAUSE_PARSER_VERSION}"
            ),
            "coverage": {
                "total_contracts": int(contract_rows[0]["total_contracts"])
                if contract_rows else 0,
                "returned_contracts": len(contracts),
                "contracts_with_text": sum(bool(item["has_text"]) for item in contracts),
            },
            "methodology": (
                "Rejected clause candidates are excluded. Unreviewed candidates "
                "retain confidence and review status and are not presented as verified."
            ),
        },
        "territory_rights": {
            "territories": territories,
            "source": "Cortellis deal territory scope",
            "coverage": {
                "total_scope_records": int(territory_rows[0]["total_scope_records"])
                if territory_rows else 0,
                "returned_scope_records": len(territories),
            },
            "methodology": (
                "Rows describe included/excluded agreement territory scope and the "
                "company's deal role. They are not asserted to be current ownership."
            ),
        },
        "comparable_transactions": {
            "comps": comps,
            "source": "Cortellis Deals",
            "coverage": {
                "total_comparable_candidates": int(
                    comp_rows[0]["total_comparable_candidates"]
                ) if comp_rows else 0,
                "returned_comparables": len(comps),
            },
            "methodology": (
                "Non-company deals are ranked deterministically against the target "
                "portfolio's dominant agreement type, therapy area, and phase at signing."
            ),
        },
        "risk_assessment": {
            "risk_flags": risk_flags,
            "source": "Derived from Cortellis deal status and counterparty concentration",
        },
    }
    built_sections = [
        build_section(section_type, section_data.get(section_type, {}))
        for section_type in sections_to_build
    ]
    return {
        "company": company_data,
        "sections": built_sections,
        "risk_flags": risk_flags,
        "metadata": {
            "total_deals_analyzed": total_deals,
            "financial_disclosure_rate": (
                f"{disclosed_count / total_deals * 100:.1f}%"
                if total_deals else "N/A"
            ),
            "financial_definition": "Known current projected totals in USD millions",
            "sources": sorted({
                section.get("source")
                for section in built_sections
                if section.get("source")
            }),
        },
    }
