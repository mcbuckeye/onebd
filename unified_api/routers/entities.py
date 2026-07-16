"""
Entity endpoints for companies, drugs, indications, technologies.
"""
from typing import Optional, List, Literal
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel
import structlog

from unified_api.services.deal_evidence_timeline import deal_evidence_timeline
from unified_api.services.company_strategy import company_strategy_intelligence

logger = structlog.get_logger(__name__)

router = APIRouter()

EntityType = Literal["company", "drug", "indication", "technology"]


class DealSummary(BaseModel):
    """Summary of a deal."""
    id: int
    title: str
    status: Optional[str] = None
    date_start: Optional[str] = None
    total_value: Optional[float] = None
    deal_type: Optional[str] = None
    agreement_type: Optional[str] = None


class EntityDetail(BaseModel):
    """Base entity detail."""
    id: int
    name: str
    deal_count: int
    deals: List[DealSummary]


class CompanyDetail(EntityDetail):
    """Company-specific details."""
    company_type: Optional[str] = None
    hq_location: Optional[str] = None
    deals_as_principal: List[DealSummary]
    deals_as_partner: List[DealSummary]
    # From entity resolution
    cik: Optional[str] = None
    ticker: Optional[str] = None


class DrugDetail(EntityDetail):
    """Drug-specific details."""
    phase_highest_start: Optional[str] = None
    phase_highest_now: Optional[str] = None


class CompanyInfo(BaseModel):
    """Company in a deal."""
    id: int
    name: str
    role: str
    company_type: Optional[str] = None
    hq_location: Optional[str] = None


class DrugInfo(BaseModel):
    """Drug in a deal."""
    id: int
    name: str
    phase_highest_now: Optional[str] = None


class EntityInfo(BaseModel):
    """Entity reference (indication, technology)."""
    id: int
    name: str


class TimelineEvent(BaseModel):
    """Timeline event."""
    event_date: Optional[str] = None
    event_type: Optional[str] = None
    stage: Optional[str] = None
    summary: Optional[str] = None


class ContractInfo(BaseModel):
    """Contract info."""
    id: int
    contract_types: Optional[str] = None
    date_filing: Optional[str] = None
    date_contract: Optional[str] = None
    has_pdf: bool = False
    has_text: bool = False


class DealSourceInfo(BaseModel):
    """Cortellis source citation linked to a deal."""
    source_id: str
    source_type: str


class FinanceSummary(BaseModel):
    """Financial summary."""
    total_paid_amount: Optional[float] = None
    total_paid_currency: Optional[str] = None
    total_paid_unit: Optional[str] = None
    total_paid_disclosure_status: Optional[str] = None
    total_projected_current_amount: Optional[float] = None
    total_projected_current_currency: Optional[str] = None
    total_projected_current_unit: Optional[str] = None
    total_projected_signing_amount: Optional[float] = None
    total_projected_signing_currency: Optional[str] = None
    total_projected_signing_unit: Optional[str] = None


class DealDetail(BaseModel):
    """Full deal details - matches frontend DealDetail interface."""
    id: int
    title: Optional[str] = None
    deal_type: Optional[str] = None
    status: Optional[str] = None
    therapy_area: Optional[str] = None
    date_start: Optional[str] = None
    date_end: Optional[str] = None
    summary: Optional[str] = None
    agreement_type: Optional[str] = None
    asset_type: Optional[str] = None
    transaction_type: Optional[str] = None
    phase_highest_start: Optional[str] = None
    phase_highest_now: Optional[str] = None
    is_merger_acquisition: Optional[bool] = None
    companies: List[CompanyInfo] = []
    indications: List[EntityInfo] = []
    technologies: List[EntityInfo] = []
    drugs: List[DrugInfo] = []
    territories_included: List[str] = []
    territories_excluded: List[str] = []
    finance: Optional[FinanceSummary] = None
    timeline: List[TimelineEvent] = []
    evidence_timeline: List[dict] = []
    evidence_timeline_summary: dict = {}
    contracts: List[ContractInfo] = []
    sources: List[DealSourceInfo] = []
    # Links to SEC filings (from Edgar BD)
    related_filings: List[dict] = []


@router.get("/entity/{entity_type}/{entity_id}")
async def get_entity(
    entity_type: EntityType = Path(...),
    entity_id: int = Path(..., gt=0),
    limit: int = 50,
):
    """
    Get detailed information about an entity.

    Returns entity details with associated deals.
    For companies, also includes CIK and ticker from entity resolution.
    """
    logger.info(
        "Getting entity",
        entity_type=entity_type,
        entity_id=entity_id,
    )

    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    with get_cortellis_session() as session:
        if entity_type == "company":
            # Get company info with xref data
            result = session.execute(text("""
                SELECT
                    c.id, c.name, c.company_type, c.hq_location,
                    COALESCE(cx.cik, c.cik) as cik,
                    COALESCE(cx.ticker, c.ticker) as ticker
                FROM companies c
                LEFT JOIN company_xref cx ON cx.cortellis_id = c.id
                WHERE c.id = :entity_id
            """), {"entity_id": entity_id})
            entity = result.fetchone()

            if not entity:
                raise HTTPException(status_code=404, detail="Company not found")

            # Get deals as principal
            principal_result = session.execute(text("""
                SELECT d.id, d.title, d.status, d.date_start::text, f.total_projected_current_amount as total_value
                FROM deal_companies dc
                JOIN deals d ON d.id = dc.deal_id
                LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
                  AND f.total_projected_current_currency = 'USD'
                  AND f.total_projected_current_unit = 'Million'
                WHERE dc.company_id = :entity_id AND dc.role = 'Principal'
                ORDER BY d.date_start DESC NULLS LAST
                LIMIT :limit
            """), {"entity_id": entity_id, "limit": limit})

            deals_as_principal = [
                DealSummary(
                    id=row.id,
                    title=row.title or "Untitled",
                    status=row.status,
                    date_start=row.date_start,
                    total_value=row.total_value
                )
                for row in principal_result
            ]

            # Get deals as partner
            partner_result = session.execute(text("""
                SELECT d.id, d.title, d.status, d.date_start::text, f.total_projected_current_amount as total_value
                FROM deal_companies dc
                JOIN deals d ON d.id = dc.deal_id
                LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
                  AND f.total_projected_current_currency = 'USD'
                  AND f.total_projected_current_unit = 'Million'
                WHERE dc.company_id = :entity_id AND dc.role = 'Partner'
                ORDER BY d.date_start DESC NULLS LAST
                LIMIT :limit
            """), {"entity_id": entity_id, "limit": limit})

            deals_as_partner = [
                DealSummary(
                    id=row.id,
                    title=row.title or "Untitled",
                    status=row.status,
                    date_start=row.date_start,
                    total_value=row.total_value
                )
                for row in partner_result
            ]

            return CompanyDetail(
                id=entity.id,
                name=entity.name,
                company_type=entity.company_type,
                hq_location=entity.hq_location,
                deal_count=len(deals_as_principal) + len(deals_as_partner),
                deals=deals_as_principal[:10] + deals_as_partner[:10],
                deals_as_principal=deals_as_principal,
                deals_as_partner=deals_as_partner,
                cik=entity.cik,
                ticker=entity.ticker,
            )

        elif entity_type == "drug":
            # Get drug info
            result = session.execute(text("""
                SELECT id, name_display as name, phase_highest_start, phase_highest_now
                FROM drugs
                WHERE id = :entity_id
            """), {"entity_id": entity_id})
            entity = result.fetchone()

            if not entity:
                raise HTTPException(status_code=404, detail="Drug not found")

            # Get deals for this drug
            deals_result = session.execute(text("""
                SELECT d.id, d.title, d.status, d.date_start::text, f.total_projected_current_amount as total_value
                FROM deal_drugs dd
                JOIN deals d ON d.id = dd.deal_id
                LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
                  AND f.total_projected_current_currency = 'USD'
                  AND f.total_projected_current_unit = 'Million'
                WHERE dd.drug_id = :entity_id
                ORDER BY d.date_start DESC NULLS LAST
                LIMIT :limit
            """), {"entity_id": entity_id, "limit": limit})

            deals = [
                DealSummary(
                    id=row.id,
                    title=row.title or "Untitled",
                    status=row.status,
                    date_start=row.date_start,
                    total_value=row.total_value
                )
                for row in deals_result
            ]

            return DrugDetail(
                id=entity.id,
                name=entity.name,
                phase_highest_start=entity.phase_highest_start,
                phase_highest_now=entity.phase_highest_now,
                deal_count=len(deals),
                deals=deals,
            )

        elif entity_type == "indication":
            # Get indication info
            result = session.execute(text("""
                SELECT id, name
                FROM indications
                WHERE id = :entity_id
            """), {"entity_id": entity_id})
            entity = result.fetchone()

            if not entity:
                raise HTTPException(status_code=404, detail="Indication not found")

            # Get deals for this indication
            deals_result = session.execute(text("""
                SELECT d.id, d.title, d.status, d.date_start::text, f.total_projected_current_amount as total_value
                FROM deal_indications di
                JOIN deals d ON d.id = di.deal_id
                LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
                  AND f.total_projected_current_currency = 'USD'
                  AND f.total_projected_current_unit = 'Million'
                WHERE di.indication_id = :entity_id
                ORDER BY d.date_start DESC NULLS LAST
                LIMIT :limit
            """), {"entity_id": entity_id, "limit": limit})

            deals = [
                DealSummary(
                    id=row.id,
                    title=row.title or "Untitled",
                    status=row.status,
                    date_start=row.date_start,
                    total_value=row.total_value
                )
                for row in deals_result
            ]

            return EntityDetail(
                id=entity.id,
                name=entity.name,
                deal_count=len(deals),
                deals=deals,
            )

        elif entity_type == "technology":
            # Get technology info
            result = session.execute(text("""
                SELECT id, name
                FROM technologies
                WHERE id = :entity_id
            """), {"entity_id": entity_id})
            entity = result.fetchone()

            if not entity:
                raise HTTPException(status_code=404, detail="Technology not found")

            # Get deals for this technology
            deals_result = session.execute(text("""
                SELECT d.id, d.title, d.status, d.date_start::text, f.total_projected_current_amount as total_value
                FROM deal_technologies dt
                JOIN deals d ON d.id = dt.deal_id
                LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
                  AND f.total_projected_current_currency = 'USD'
                  AND f.total_projected_current_unit = 'Million'
                WHERE dt.technology_id = :entity_id
                ORDER BY d.date_start DESC NULLS LAST
                LIMIT :limit
            """), {"entity_id": entity_id, "limit": limit})

            deals = [
                DealSummary(
                    id=row.id,
                    title=row.title or "Untitled",
                    status=row.status,
                    date_start=row.date_start,
                    total_value=row.total_value
                )
                for row in deals_result
            ]

            return EntityDetail(
                id=entity.id,
                name=entity.name,
                deal_count=len(deals),
                deals=deals,
            )


@router.get("/deal/{deal_id}", response_model=DealDetail)
async def get_deal(deal_id: int = Path(..., gt=0)):
    """
    Get full deal details including related SEC filings.

    Returns:
    - Deal metadata from Cortellis
    - Associated companies, drugs, indications, technologies
    - Timeline events
    - Territory coverage
    - Financial details
    - Contracts
    - Related SEC 8-K filings (if matched)
    """
    logger.info("Getting deal", deal_id=deal_id)

    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session
    from unified_api.services.cortellis_deal_api_sync import (
        ensure_deal_api_scan_schema,
    )

    ensure_deal_api_scan_schema()

    with get_cortellis_session() as session:
        # 1. Get deal basic info
        deal_result = session.execute(text("""
            SELECT
                d.id,
                d.title,
                d.deal_type,
                d.summary,
                d.status,
                d.date_start::text,
                d.date_end::text,
                ta.name as therapy_area,
                d.agreement_type,
                d.asset_type,
                d.transaction_type,
                d.phase_highest_start,
                d.phase_highest_now,
                d.is_merger_acquisition,
                f.total_projected_current_amount,
                f.total_projected_current_currency,
                f.total_projected_current_unit,
                f.total_projected_signing_amount,
                f.total_projected_signing_currency,
                f.total_projected_signing_unit,
                f.total_paid_amount,
                f.total_paid_currency,
                f.total_paid_unit,
                f.total_paid_disclosure_status
            FROM deals d
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
            LEFT JOIN therapy_areas ta ON ta.id = d.therapy_area_id
            WHERE d.id = :deal_id
        """), {"deal_id": deal_id})
        deal = deal_result.fetchone()

        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")

        # 2. Get companies
        companies_result = session.execute(text("""
            SELECT
                c.id,
                c.name,
                c.company_type,
                c.hq_location,
                dc.role
            FROM deal_companies dc
            JOIN companies c ON c.id = dc.company_id
            WHERE dc.deal_id = :deal_id
        """), {"deal_id": deal_id})

        companies = [
            CompanyInfo(
                id=row.id,
                name=row.name,
                role=row.role,
                company_type=row.company_type,
                hq_location=row.hq_location,
            )
            for row in companies_result
        ]

        # 3. Get drugs
        drugs_result = session.execute(text("""
            SELECT
                dr.id,
                dr.name_display as name,
                dr.phase_highest_now
            FROM deal_drugs dd
            JOIN drugs dr ON dr.id = dd.drug_id
            WHERE dd.deal_id = :deal_id
        """), {"deal_id": deal_id})

        drugs = [
            DrugInfo(id=row.id, name=row.name, phase_highest_now=row.phase_highest_now)
            for row in drugs_result
        ]

        # 4. Get indications
        indications_result = session.execute(text("""
            SELECT
                i.id,
                i.name
            FROM deal_indications di
            JOIN indications i ON i.id = di.indication_id
            WHERE di.deal_id = :deal_id
        """), {"deal_id": deal_id})

        indications = [
            EntityInfo(id=row.id, name=row.name)
            for row in indications_result
        ]

        # 5. Get technologies
        technologies_result = session.execute(text("""
            SELECT
                t.id,
                t.name
            FROM deal_technologies dt
            JOIN technologies t ON t.id = dt.technology_id
            WHERE dt.deal_id = :deal_id
        """), {"deal_id": deal_id})

        technologies = [
            EntityInfo(id=row.id, name=row.name)
            for row in technologies_result
        ]

        # 6. Get territories (split by included/excluded)
        territories_result = session.execute(text("""
            SELECT
                t.name,
                dt.territory_type as type
            FROM deal_territories dt
            JOIN territories t ON t.id = dt.territory_id
            WHERE dt.deal_id = :deal_id
        """), {"deal_id": deal_id})

        territories_included = []
        territories_excluded = []
        for row in territories_result:
            if row.type and 'exclu' in row.type.lower():
                territories_excluded.append(row.name)
            else:
                territories_included.append(row.name)

        # 7. Get timeline events
        timeline_result = session.execute(text("""
            SELECT
                event_date::text,
                event_type,
                stage,
                summary
            FROM deal_timeline_events
            WHERE deal_id = :deal_id
            ORDER BY event_date DESC
        """), {"deal_id": deal_id})

        timeline = [
            TimelineEvent(
                event_date=row.event_date,
                event_type=row.event_type,
                stage=row.stage,
                summary=row.summary,
            )
            for row in timeline_result
        ]

        # 8. Get contracts
        contracts_result = session.execute(text("""
            SELECT
                id,
                contract_types,
                date_filing::text,
                date_contract::text,
                has_pdf,
                has_text
            FROM deal_contracts
            WHERE deal_id = :deal_id
        """), {"deal_id": deal_id})

        contracts = [
            ContractInfo(
                id=row.id,
                contract_types=row.contract_types,
                date_filing=row.date_filing,
                date_contract=row.date_contract,
                has_pdf=row.has_pdf or False,
                has_text=row.has_text or False,
            )
            for row in contracts_result
        ]

        # 9. Get current Cortellis source citations.
        sources_result = session.execute(text("""
            SELECT source_id, source_type
            FROM cortellis_deal_sources
            WHERE deal_id = :deal_id
              AND is_current
            ORDER BY source_type, source_id
        """), {"deal_id": deal_id})
        sources = [
            DealSourceInfo(
                source_id=row.source_id,
                source_type=row.source_type,
            )
            for row in sources_result
        ]

        # Merge explicit Cortellis milestones with only directly cited NCT trials.
        evidence_timeline_result = deal_evidence_timeline(session, deal_id)

        # Build finance summary if any financial data exists
        finance = None
        if any(
            value is not None
            for value in (
                deal.total_projected_current_amount,
                deal.total_projected_signing_amount,
                deal.total_paid_amount,
            )
        ):
            finance = FinanceSummary(
                total_paid_amount=float(deal.total_paid_amount) if deal.total_paid_amount is not None else None,
                total_paid_currency=deal.total_paid_currency,
                total_paid_unit=deal.total_paid_unit,
                total_paid_disclosure_status=deal.total_paid_disclosure_status,
                total_projected_current_amount=float(deal.total_projected_current_amount) if deal.total_projected_current_amount is not None else None,
                total_projected_current_currency=deal.total_projected_current_currency,
                total_projected_current_unit=deal.total_projected_current_unit,
                total_projected_signing_amount=float(deal.total_projected_signing_amount) if deal.total_projected_signing_amount is not None else None,
                total_projected_signing_currency=deal.total_projected_signing_currency,
                total_projected_signing_unit=deal.total_projected_signing_unit,
            )

        return DealDetail(
            id=deal.id,
            title=deal.title,
            deal_type=deal.deal_type,
            status=deal.status,
            therapy_area=deal.therapy_area,
            date_start=deal.date_start,
            date_end=deal.date_end,
            summary=deal.summary,
            agreement_type=deal.agreement_type,
            asset_type=deal.asset_type,
            transaction_type=deal.transaction_type,
            phase_highest_start=deal.phase_highest_start,
            phase_highest_now=deal.phase_highest_now,
            is_merger_acquisition=deal.is_merger_acquisition,
            companies=companies,
            indications=indications,
            technologies=technologies,
            drugs=drugs,
            territories_included=territories_included,
            territories_excluded=territories_excluded,
            finance=finance,
            timeline=timeline,
            evidence_timeline=(evidence_timeline_result or {}).get("events", []),
            evidence_timeline_summary=(
                (evidence_timeline_result or {}).get("summary", {})
            ),
            contracts=contracts,
            sources=sources,
            related_filings=[],  # TODO: From Edgar via Neo4j
        )


@router.get("/deal/{deal_id}/evidence-timeline")
async def get_deal_evidence_timeline(deal_id: int = Path(..., gt=0)):
    """Return source-labeled deal, regulatory, and exactly cited trial events."""
    from unified_api.services.database import get_cortellis_session

    with get_cortellis_session() as session:
        result = deal_evidence_timeline(session, deal_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return result


class PartnerSummary(BaseModel):
    """Summary of a partnership relationship."""
    company_id: int
    company_name: str
    deal_count: int
    total_value: Optional[float] = None


class TherapeuticFocus(BaseModel):
    """Therapeutic area/indication distribution."""
    indication: str
    deal_count: int


class DealsByYear(BaseModel):
    """Deals grouped by year."""
    year: int
    deal_count: int
    total_value: Optional[float] = None


class DrugAssetSummary(BaseModel):
    """Summary of a drug/asset."""
    id: int
    name: str
    phase_current: Optional[str] = None
    deal_count: int


class SecFilingSummary(BaseModel):
    """Summary of SEC filing."""
    id: int
    doc_type: Optional[str] = None
    title: Optional[str] = None
    filing_date: Optional[str] = None
    url: Optional[str] = None


def _get_recent_sec_filings(session, company_id: int) -> List[SecFilingSummary]:
    """Return recent SEC documents with their actual form types and filing dates."""
    from sqlalchemy import text

    result = session.execute(text("""
        SELECT
            d.id,
            COALESCE(NULLIF(d.subtype, ''), NULLIF(d.doc_type, '')) AS doc_type,
            d.title,
            r.filing_date::date::text AS filing_date,
            r.url
        FROM documents d
        JOIN raw_documents r ON d.raw_document_id = r.id
        WHERE r.company_id = :company_id
        ORDER BY r.filing_date DESC NULLS LAST, d.id DESC
        LIMIT 10
    """), {"company_id": company_id})

    return [
        SecFilingSummary(
            id=row.id,
            doc_type=row.doc_type,
            title=row.title,
            filing_date=row.filing_date,
            url=row.url,
        )
        for row in result
    ]


class EdgarDealSummary(BaseModel):
    """Summary of Edgar-extracted deal."""
    id: int
    deal_type: str
    announced_at: Optional[str] = None
    description: Optional[str] = None


class CompanyProfile(BaseModel):
    """Comprehensive company intelligence profile."""
    # Basic info
    id: int
    name: str
    company_type: Optional[str] = None
    hq_location: Optional[str] = None

    # Entity resolution
    cik: Optional[str] = None
    ticker: Optional[str] = None

    # Deal statistics (Cortellis)
    total_deals: int
    deals_as_principal: int
    deals_as_partner: int

    # Financial summary
    avg_deal_value: Optional[float] = None
    total_deal_value: Optional[float] = None
    deals_with_disclosed_value: int
    financial_value_unit: str = "USD millions"

    # Timeline
    deals_by_year: List[DealsByYear]

    # Partners
    top_partners: List[PartnerSummary]

    # Therapeutic focus
    therapeutic_focus: List[TherapeuticFocus]

    # Recent activity (last 12 months)
    recent_deals: List[DealSummary]

    # Associated assets
    drugs: List[DrugAssetSummary]

    # Edgar SEC data (if CIK matched)
    edgar_company_id: Optional[int] = None
    sec_filings_count: int = 0
    recent_sec_filings: List[SecFilingSummary] = []
    edgar_deals: List[EdgarDealSummary] = []


@router.get("/company/{company_id}/profile", response_model=CompanyProfile)
async def get_company_profile(company_id: int = Path(..., gt=0)):
    """
    Get comprehensive company intelligence profile.

    Returns:
    - Company overview
    - Deal history and timeline
    - Top partners
    - Therapeutic focus distribution
    - Average deal values
    - SEC filings (if matched via CIK)
    """
    logger.info("Getting company profile", company_id=company_id)

    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    with get_cortellis_session() as session:
        # 1. Get company basic info with xref data
        company_result = session.execute(text("""
            SELECT
                c.id, c.name, c.company_type, c.hq_location,
                COALESCE(cx.cik, c.cik) as cik,
                COALESCE(cx.ticker, c.ticker) as ticker
            FROM companies c
            LEFT JOIN company_xref cx ON cx.cortellis_id = c.id
            WHERE c.id = :company_id
        """), {"company_id": company_id})
        company = company_result.fetchone()

        if not company:
            raise HTTPException(status_code=404, detail="Company not found")

        # 2. Get deal counts by role
        deal_counts = session.execute(text("""
            SELECT
                COUNT(DISTINCT deal_id) AS total_deals,
                COUNT(DISTINCT deal_id) FILTER (
                    WHERE LOWER(COALESCE(role, '')) = 'principal'
                ) AS deals_as_principal,
                COUNT(DISTINCT deal_id) FILTER (
                    WHERE LOWER(COALESCE(role, '')) = 'partner'
                ) AS deals_as_partner
            FROM deal_companies
            WHERE company_id = :company_id
        """), {"company_id": company_id}).one()

        deals_as_principal = int(deal_counts.deals_as_principal or 0)
        deals_as_partner = int(deal_counts.deals_as_partner or 0)
        total_deals = int(deal_counts.total_deals or 0)

        # 3. Get financial summary
        financial_result = session.execute(text("""
            WITH company_deals AS (
                SELECT DISTINCT deal_id
                FROM deal_companies
                WHERE company_id = :company_id
            )
            SELECT
                AVG(f.total_projected_current_amount) as avg_value,
                SUM(f.total_projected_current_amount) as total_value,
                COUNT(f.total_projected_current_amount) as disclosed_count
            FROM company_deals cd
            JOIN deal_finance_summary f ON f.deal_id = cd.deal_id
            WHERE f.total_projected_current_amount IS NOT NULL
              AND f.total_projected_current_currency = 'USD'
              AND f.total_projected_current_unit = 'Million'
        """), {"company_id": company_id})
        financial = financial_result.fetchone()

        # 4. Get deals by year
        deals_by_year_result = session.execute(text("""
            WITH company_deals AS (
                SELECT DISTINCT deal_id
                FROM deal_companies
                WHERE company_id = :company_id
            )
            SELECT
                EXTRACT(YEAR FROM d.date_start)::int as year,
                COUNT(DISTINCT d.id) as deal_count,
                SUM(f.total_projected_current_amount) as total_value
            FROM company_deals cd
            JOIN deals d ON d.id = cd.deal_id
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
              AND f.total_projected_current_currency = 'USD'
              AND f.total_projected_current_unit = 'Million'
            WHERE d.date_start IS NOT NULL
            GROUP BY EXTRACT(YEAR FROM d.date_start)
            ORDER BY year DESC
            LIMIT 20
        """), {"company_id": company_id})

        deals_by_year = [
            DealsByYear(
                year=row.year,
                deal_count=row.deal_count,
                total_value=row.total_value
            )
            for row in deals_by_year_result
        ]

        # 5. Get top partners
        top_partners_result = session.execute(text("""
            WITH focal_deals AS (
                SELECT DISTINCT deal_id
                FROM deal_companies
                WHERE company_id = :company_id
            ), partner_deals AS (
                SELECT DISTINCT fd.deal_id, dc.company_id
                FROM focal_deals fd
                JOIN deal_companies dc ON dc.deal_id = fd.deal_id
                WHERE dc.company_id <> :company_id
            )
            SELECT
                c2.id as partner_id,
                c2.name as partner_name,
                COUNT(*) as deal_count,
                SUM(f.total_projected_current_amount) as total_value
            FROM partner_deals pd
            JOIN companies c2 ON c2.id = pd.company_id
            LEFT JOIN deal_finance_summary f ON f.deal_id = pd.deal_id
              AND f.total_projected_current_currency = 'USD'
              AND f.total_projected_current_unit = 'Million'
            GROUP BY c2.id, c2.name
            ORDER BY deal_count DESC
            LIMIT 10
        """), {"company_id": company_id})

        top_partners = [
            PartnerSummary(
                company_id=row.partner_id,
                company_name=row.partner_name,
                deal_count=row.deal_count,
                total_value=row.total_value
            )
            for row in top_partners_result
        ]

        # 6. Get therapeutic focus (indications)
        therapeutic_result = session.execute(text("""
            WITH company_deals AS (
                SELECT DISTINCT deal_id
                FROM deal_companies
                WHERE company_id = :company_id
            )
            SELECT
                i.name as indication,
                COUNT(DISTINCT di.deal_id) as deal_count
            FROM company_deals cd
            JOIN deal_indications di ON di.deal_id = cd.deal_id
            JOIN indications i ON i.id = di.indication_id
            GROUP BY i.name
            ORDER BY deal_count DESC
            LIMIT 15
        """), {"company_id": company_id})

        therapeutic_focus = [
            TherapeuticFocus(
                indication=row.indication,
                deal_count=row.deal_count
            )
            for row in therapeutic_result
        ]

        # 7. Get recent deals (last 12 months)
        recent_deals_result = session.execute(text("""
            WITH company_deals AS (
                SELECT DISTINCT deal_id
                FROM deal_companies
                WHERE company_id = :company_id
            )
            SELECT
                d.id,
                d.title,
                d.status,
                d.date_start::text,
                d.deal_type,
                d.agreement_type,
                f.total_projected_current_amount as total_value
            FROM company_deals cd
            JOIN deals d ON d.id = cd.deal_id
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
              AND f.total_projected_current_currency = 'USD'
              AND f.total_projected_current_unit = 'Million'
            WHERE d.date_start >= CURRENT_DATE - INTERVAL '12 months'
            ORDER BY d.date_start DESC
            LIMIT 20
        """), {"company_id": company_id})

        recent_deals = [
            DealSummary(
                id=row.id,
                title=row.title or "Untitled",
                status=row.status,
                date_start=row.date_start,
                total_value=row.total_value,
                deal_type=row.deal_type,
                agreement_type=row.agreement_type,
            )
            for row in recent_deals_result
        ]

        # 8. Get associated drugs
        drugs_result = session.execute(text("""
            SELECT
                dr.id,
                dr.name_display as name,
                dr.phase_highest_now as phase_current,
                COUNT(DISTINCT dd.deal_id) as deal_count
            FROM deal_companies dc
            JOIN deal_drugs dd ON dd.deal_id = dc.deal_id
            JOIN drugs dr ON dr.id = dd.drug_id
            WHERE dc.company_id = :company_id
            GROUP BY dr.id, dr.name_display, dr.phase_highest_now
            ORDER BY deal_count DESC
            LIMIT 20
        """), {"company_id": company_id})

        drugs = [
            DrugAssetSummary(
                id=row.id,
                name=row.name,
                phase_current=row.phase_current,
                deal_count=row.deal_count
            )
            for row in drugs_result
        ]

        # 9. Get Edgar SEC data if CIK is available
        edgar_company_id = None
        sec_filings_count = 0
        recent_sec_filings = []
        edgar_deals = []

        if company.cik:
            try:
                from unified_api.services.database import get_edgar_session

                with get_edgar_session() as edgar_session:
                    # Find Edgar company by CIK
                    edgar_company = edgar_session.execute(text("""
                        SELECT id FROM companies WHERE cik = :cik
                    """), {"cik": company.cik}).fetchone()

                    if edgar_company:
                        edgar_company_id = edgar_company.id

                        # Get filing count
                        count_result = edgar_session.execute(text("""
                            SELECT COUNT(*) FROM raw_documents
                            WHERE company_id = :company_id
                        """), {"company_id": edgar_company_id})
                        sec_filings_count = count_result.scalar() or 0

                        recent_sec_filings = _get_recent_sec_filings(
                            edgar_session,
                            edgar_company_id,
                        )

                        # Get Edgar-extracted deals for this company
                        deals_result = edgar_session.execute(text("""
                            SELECT
                                d.id,
                                d.deal_type,
                                d.announced_at,
                                d.description
                            FROM deals d
                            JOIN deal_parties dp ON dp.deal_id = d.id
                            WHERE dp.company_id = :company_id
                            ORDER BY d.announced_at DESC NULLS LAST
                            LIMIT 10
                        """), {"company_id": edgar_company_id})

                        edgar_deals = [
                            EdgarDealSummary(
                                id=row.id,
                                deal_type=row.deal_type,
                                announced_at=str(row.announced_at) if row.announced_at else None,
                                description=row.description[:200] + "..." if row.description and len(row.description) > 200 else row.description,
                            )
                            for row in deals_result
                        ]
            except Exception as e:
                logger.error("Failed to fetch Edgar data", error=str(e), cik=company.cik)

        return CompanyProfile(
            id=company.id,
            name=company.name,
            company_type=company.company_type,
            hq_location=company.hq_location,
            cik=company.cik,
            ticker=company.ticker,
            total_deals=total_deals,
            deals_as_principal=deals_as_principal,
            deals_as_partner=deals_as_partner,
            avg_deal_value=(
                float(financial.avg_value)
                if financial and financial.avg_value is not None else None
            ),
            total_deal_value=(
                float(financial.total_value)
                if financial and financial.total_value is not None else None
            ),
            deals_with_disclosed_value=financial.disclosed_count if financial else 0,
            financial_value_unit="USD millions",
            deals_by_year=deals_by_year,
            top_partners=top_partners,
            therapeutic_focus=therapeutic_focus,
            recent_deals=recent_deals,
            drugs=drugs,
            edgar_company_id=edgar_company_id,
            sec_filings_count=sec_filings_count,
            recent_sec_filings=recent_sec_filings,
            edgar_deals=edgar_deals,
        )


@router.get("/company/{company_id}/strategy-intelligence")
async def get_company_strategy_intelligence(
    company_id: int = Path(..., gt=0),
    years: int = Query(default=5, ge=1, le=20),
    peer_limit: int = Query(default=10, ge=1, le=25),
    entrant_days: int = Query(default=365, ge=30, le=1825),
):
    """Return grounded deal patterns, overlap peers, and observed entrants."""
    from unified_api.services.database import get_cortellis_session

    with get_cortellis_session() as session:
        result = company_strategy_intelligence(
            session,
            company_id,
            years=years,
            peer_limit=peer_limit,
            entrant_days=entrant_days,
        )
    if result is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return result


# ============================================
# Drug/Asset Profile
# ============================================

class TerritoryRights(BaseModel):
    """Latest deal-scope evidence for a territory (not current ownership)."""
    territory: str
    scope_type: Optional[str] = None
    deal_status: Optional[str] = None
    deal_participants: List[str] = []
    evidence_note: str = "Deal scope only; current ownership is not established"
    # Deprecated compatibility fields. A deal participant is not necessarily a
    # current rights holder, so new responses intentionally leave these null.
    rights_holder: Optional[str] = None
    rights_holder_id: Optional[int] = None
    deal_id: Optional[int] = None
    deal_title: Optional[str] = None


class DrugDealSummary(BaseModel):
    """Summary of a deal involving a drug."""
    id: int
    title: Optional[str] = None
    deal_type: Optional[str] = None
    status: Optional[str] = None
    date_start: Optional[str] = None
    total_value: Optional[float] = None
    principal_company: Optional[str] = None
    principal_company_id: Optional[int] = None
    partner_company: Optional[str] = None
    partner_company_id: Optional[int] = None
    indications: List[str] = []
    territories: List[str] = []


class DrugProfile(BaseModel):
    """Comprehensive drug/asset intelligence profile."""
    # Basic info
    id: int
    name: str
    phase_highest_start: Optional[str] = None
    phase_highest_now: Optional[str] = None

    # Deal statistics
    total_deals: int
    total_deal_value: Optional[float] = None
    avg_deal_value: Optional[float] = None
    deals_with_disclosed_value: int

    # Timeline
    deals_by_year: List[DealsByYear]

    # Deal territory-scope evidence (legacy response key retained for compatibility)
    rights_holders: List[TerritoryRights]

    # Deal history
    deals: List[DrugDealSummary]

    # Indications targeted
    indications: List[str]

    # Technologies/modalities
    technologies: List[str]


@router.get("/drug/{drug_id}/profile", response_model=DrugProfile)
async def get_drug_profile(drug_id: int = Path(..., gt=0)):
    """
    Get comprehensive drug/asset intelligence profile.

    Returns:
    - Drug overview (phase, mechanism, type)
    - Complete deal history
    - Latest deal territory-scope evidence (not current ownership)
    - Financial summary across all deals
    - Indications and technologies
    """
    logger.info("Getting drug profile", drug_id=drug_id)

    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    with get_cortellis_session() as session:
        # 1. Get drug basic info
        drug_result = session.execute(text("""
            SELECT
                id,
                name_display as name,
                phase_highest_start,
                phase_highest_now
            FROM drugs
            WHERE id = :drug_id
        """), {"drug_id": drug_id})
        drug = drug_result.fetchone()

        if not drug:
            raise HTTPException(status_code=404, detail="Drug not found")

        # 2. Get deal statistics
        stats_result = session.execute(text("""
            SELECT
                COUNT(DISTINCT dd.deal_id) as total_deals,
                SUM(f.total_projected_current_amount) as total_value,
                AVG(f.total_projected_current_amount) as avg_value,
                COUNT(f.total_projected_current_amount) as disclosed_count
            FROM deal_drugs dd
            LEFT JOIN deal_finance_summary f ON f.deal_id = dd.deal_id
              AND f.total_projected_current_currency = 'USD'
              AND f.total_projected_current_unit = 'Million'
            WHERE dd.drug_id = :drug_id
        """), {"drug_id": drug_id})
        stats = stats_result.fetchone()

        # 3. Get deals by year
        deals_by_year_result = session.execute(text("""
            SELECT
                EXTRACT(YEAR FROM d.date_start)::int as year,
                COUNT(*) as deal_count,
                SUM(f.total_projected_current_amount) as total_value
            FROM deal_drugs dd
            JOIN deals d ON d.id = dd.deal_id
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
              AND f.total_projected_current_currency = 'USD'
              AND f.total_projected_current_unit = 'Million'
            WHERE dd.drug_id = :drug_id
              AND d.date_start IS NOT NULL
            GROUP BY EXTRACT(YEAR FROM d.date_start)
            ORDER BY year DESC
        """), {"drug_id": drug_id})

        deals_by_year = [
            DealsByYear(
                year=row.year,
                deal_count=row.deal_count,
                total_value=row.total_value
            )
            for row in deals_by_year_result
        ]

        # 4. Get recent deal-scope evidence per territory and scope type. Do not
        # infer current ownership from a party's role in a deal record.
        rights_result = session.execute(text("""
            WITH ranked_rights AS (
                SELECT
                    t.name as territory,
                    dt.territory_type as scope_type,
                    d.status as deal_status,
                    (SELECT ARRAY_AGG(c.name || CASE
                        WHEN dc.role IS NOT NULL THEN ' (' || dc.role || ')'
                        ELSE '' END ORDER BY dc.role, c.name)
                     FROM deal_companies dc
                     JOIN companies c ON c.id = dc.company_id
                     WHERE dc.deal_id = d.id) as deal_participants,
                    d.id as deal_id,
                    d.title as deal_title,
                    d.date_start,
                    ROW_NUMBER() OVER (
                        PARTITION BY t.name, COALESCE(dt.territory_type, '')
                        ORDER BY d.date_start DESC NULLS LAST, d.id DESC
                    ) as rn
                FROM deal_drugs dd
                JOIN deals d ON d.id = dd.deal_id
                JOIN deal_territories dt ON dt.deal_id = d.id
                JOIN territories t ON t.id = dt.territory_id
                WHERE dd.drug_id = :drug_id
            )
            SELECT territory, scope_type, deal_status, deal_participants,
                   deal_id, deal_title
            FROM ranked_rights
            WHERE rn = 1
            ORDER BY territory
            LIMIT 50
        """), {"drug_id": drug_id})

        rights_holders = [
            TerritoryRights(
                territory=row.territory,
                scope_type=row.scope_type,
                deal_status=row.deal_status,
                deal_participants=row.deal_participants or [],
                deal_id=row.deal_id,
                deal_title=row.deal_title,
            )
            for row in rights_result
        ]

        # 5. Get all deals for this drug
        deals_result = session.execute(text("""
            SELECT
                d.id,
                d.title,
                d.deal_type,
                d.status,
                d.date_start::text,
                f.total_projected_current_amount as total_value,
                (SELECT c.name FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal_company,
                (SELECT c.id FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal_company_id,
                (SELECT c.name FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner_company,
                (SELECT c.id FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner_company_id,
                (SELECT array_agg(i.name)
                 FROM deal_indications di
                 JOIN indications i ON i.id = di.indication_id
                 WHERE di.deal_id = d.id) as indications,
                (SELECT array_agg(t.name)
                 FROM deal_territories dt
                 JOIN territories t ON t.id = dt.territory_id
                 WHERE dt.deal_id = d.id AND dt.territory_type NOT ILIKE '%exclu%') as territories
            FROM deal_drugs dd
            JOIN deals d ON d.id = dd.deal_id
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
              AND f.total_projected_current_currency = 'USD'
              AND f.total_projected_current_unit = 'Million'
            WHERE dd.drug_id = :drug_id
            ORDER BY d.date_start DESC NULLS LAST
            LIMIT 100
        """), {"drug_id": drug_id})

        deals = [
            DrugDealSummary(
                id=row.id,
                title=row.title,
                deal_type=row.deal_type,
                status=row.status,
                date_start=row.date_start,
                total_value=float(row.total_value) if row.total_value is not None else None,
                principal_company=row.principal_company,
                principal_company_id=row.principal_company_id,
                partner_company=row.partner_company,
                partner_company_id=row.partner_company_id,
                indications=row.indications or [],
                territories=(row.territories or [])[:10],
            )
            for row in deals_result
        ]

        # 6. Get all indications for this drug
        indications_result = session.execute(text("""
            SELECT DISTINCT i.name
            FROM deal_drugs dd
            JOIN deal_indications di ON di.deal_id = dd.deal_id
            JOIN indications i ON i.id = di.indication_id
            WHERE dd.drug_id = :drug_id
            ORDER BY i.name
        """), {"drug_id": drug_id})

        indications = [row.name for row in indications_result]

        # 7. Get all technologies for this drug
        technologies_result = session.execute(text("""
            SELECT DISTINCT t.name
            FROM deal_drugs dd
            JOIN deal_technologies dt ON dt.deal_id = dd.deal_id
            JOIN technologies t ON t.id = dt.technology_id
            WHERE dd.drug_id = :drug_id
            ORDER BY t.name
        """), {"drug_id": drug_id})

        technologies = [row.name for row in technologies_result]

        return DrugProfile(
            id=drug.id,
            name=drug.name,
            phase_highest_start=drug.phase_highest_start,
            phase_highest_now=drug.phase_highest_now,
            total_deals=stats.total_deals or 0,
            total_deal_value=float(stats.total_value) if stats.total_value is not None else None,
            avg_deal_value=float(stats.avg_value) if stats.avg_value is not None else None,
            deals_with_disclosed_value=stats.disclosed_count or 0,
            deals_by_year=deals_by_year,
            rights_holders=rights_holders,
            deals=deals,
            indications=indications,
            technologies=technologies,
        )
