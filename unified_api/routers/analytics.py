"""
Analytics endpoints for market trends, valuations, and benchmarks.

Dashboard endpoints:
- Market trends (time series)
- Valuations by phase/indication/deal-type
- Top deals and acquirers
- Deal activity summary
- Geographic distribution
- Agreement type breakdown
- Deal status funnel
- Therapy area heatmap
- M&A analytics (premium, share price impact)
- Company comparison (head-to-head)
- Year-over-year growth
"""
from typing import Optional, List
from fastapi import APIRouter, Query
from pydantic import BaseModel
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()


@router.get("/analytics/metric-definitions")
async def metric_definitions():
    """Return the governed semantic contract for financial and count metrics."""
    from unified_api.services.governed_metrics import METRIC_DEFINITIONS

    return {"metrics": METRIC_DEFINITIONS, "version": 1}


class TrendDataPoint(BaseModel):
    """A single data point in a time series."""
    period: str  # YYYY or YYYY-QN
    deal_count: int
    total_value: Optional[float] = None
    avg_value: Optional[float] = None
    disclosed_count: int = 0


class MarketTrendsResponse(BaseModel):
    """Market trends over time."""
    granularity: str  # "year" or "quarter"
    data: List[TrendDataPoint]
    filters_applied: dict


class ValuationBenchmark(BaseModel):
    """Valuation statistics for a category."""
    category: str
    deal_count: int
    disclosed_count: int
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    avg_value: Optional[float] = None
    median_value: Optional[float] = None
    q1_value: Optional[float] = None  # 25th percentile
    q3_value: Optional[float] = None  # 75th percentile


class ValuationBenchmarksResponse(BaseModel):
    """Valuation benchmarks by category."""
    benchmark_type: str  # "phase", "indication", "deal_type", "technology"
    benchmarks: List[ValuationBenchmark]


class TopDeal(BaseModel):
    """A top deal by value."""
    id: int
    title: str
    total_value: float
    date_start: Optional[str] = None
    deal_type: Optional[str] = None
    principal_company: Optional[str] = None
    partner_company: Optional[str] = None


@router.get("/analytics/market-trends", response_model=MarketTrendsResponse)
async def get_market_trends(
    granularity: str = Query("year", enum=["year", "quarter"]),
    therapy_area: Optional[str] = None,
    indication: Optional[str] = None,
    deal_type: Optional[str] = None,
    technology: Optional[str] = None,
    company: Optional[str] = None,
    years: int = Query(10, ge=1, le=30, description="Number of years to include"),
):
    """
    Get deal activity trends over time.

    Returns time series data of deal counts and values,
    filterable by therapy area, indication, deal type, etc.

    Perfect for trend analysis and market landscape charts.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info(
        "Getting market trends",
        granularity=granularity,
        therapy_area=therapy_area,
        indication=indication,
    )

    # Build filter conditions
    conditions = ["d.date_start IS NOT NULL"]
    params = {"years": years}

    if therapy_area:
        conditions.append("""
            d.id IN (
                SELECT di.deal_id FROM deal_indications di
                JOIN indications i ON i.id = di.indication_id
                WHERE i.name ILIKE :therapy_area
            )
        """)
        params["therapy_area"] = f"%{therapy_area}%"

    if indication:
        conditions.append("""
            d.id IN (
                SELECT di.deal_id FROM deal_indications di
                JOIN indications i ON i.id = di.indication_id
                WHERE i.name ILIKE :indication
            )
        """)
        params["indication"] = f"%{indication}%"

    if deal_type:
        conditions.append("d.deal_type ILIKE :deal_type")
        params["deal_type"] = f"%{deal_type}%"

    if technology:
        conditions.append("""
            d.id IN (
                SELECT dt.deal_id FROM deal_technologies dt
                JOIN technologies t ON t.id = dt.technology_id
                WHERE t.name ILIKE :technology
            )
        """)
        params["technology"] = f"%{technology}%"

    if company:
        conditions.append("""
            d.id IN (
                SELECT dc.deal_id FROM deal_companies dc
                JOIN companies c ON c.id = dc.company_id
                WHERE c.name ILIKE :company
            )
        """)
        params["company"] = f"%{company}%"

    where_clause = " AND ".join(conditions)

    # Build period extraction based on granularity
    if granularity == "quarter":
        period_expr = "EXTRACT(YEAR FROM d.date_start)::int || '-Q' || EXTRACT(QUARTER FROM d.date_start)::int"
        order_expr = "EXTRACT(YEAR FROM d.date_start), EXTRACT(QUARTER FROM d.date_start)"
    else:
        period_expr = "EXTRACT(YEAR FROM d.date_start)::int::text"
        order_expr = "EXTRACT(YEAR FROM d.date_start)"

    query = f"""
        SELECT
            {period_expr} as period,
            COUNT(*) as deal_count,
            SUM(f.total_projected_current_amount) as total_value,
            AVG(f.total_projected_current_amount) as avg_value,
            COUNT(f.total_projected_current_amount) as disclosed_count
        FROM deals d
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE {where_clause}
          AND d.date_start >= CURRENT_DATE - INTERVAL ':years years'
        GROUP BY {order_expr}
        ORDER BY {order_expr} DESC
    """

    # Fix interval syntax - can't use parameter in interval
    query = query.replace(":years years", f"{years} years")

    with get_cortellis_session() as session:
        result = session.execute(text(query), params)

        data = [
            TrendDataPoint(
                period=str(row.period),
                deal_count=row.deal_count,
                total_value=float(row.total_value) if row.total_value is not None else None,
                avg_value=float(row.avg_value) if row.avg_value is not None else None,
                disclosed_count=row.disclosed_count,
            )
            for row in result
        ]

    filters_applied = {
        k: v for k, v in {
            "therapy_area": therapy_area,
            "indication": indication,
            "deal_type": deal_type,
            "technology": technology,
            "company": company,
            "years": years,
        }.items() if v is not None
    }

    return MarketTrendsResponse(
        granularity=granularity,
        data=data,
        filters_applied=filters_applied,
    )


@router.get("/analytics/valuations/by-phase", response_model=ValuationBenchmarksResponse)
async def get_valuations_by_phase(
    therapy_area: Optional[str] = None,
    indication: Optional[str] = None,
    years: int = Query(5, ge=1, le=20),
):
    """
    Get valuation benchmarks by development phase.

    Shows deal value statistics (min, max, avg, median, quartiles)
    for each development phase at time of deal.

    Essential for understanding phase-appropriate valuations.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Getting valuations by phase", indication=indication)

    # Phase info is in deal_timeline_events.stage, not deals table
    # Get the earliest stage for each deal (phase at deal announcement)
    query = f"""
        WITH deal_phases AS (
            SELECT DISTINCT ON (dte.deal_id)
                dte.deal_id,
                dte.stage
            FROM deal_timeline_events dte
            WHERE dte.stage IS NOT NULL AND dte.stage != ''
            ORDER BY dte.deal_id, dte.event_date ASC
        )
        SELECT
            dp.stage as phase,
            COUNT(*) as deal_count,
            COUNT(f.total_projected_current_amount) as disclosed_count,
            MIN(f.total_projected_current_amount) as min_value,
            MAX(f.total_projected_current_amount) as max_value,
            AVG(f.total_projected_current_amount) as avg_value,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.total_projected_current_amount) as median_value,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY f.total_projected_current_amount) as q1_value,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY f.total_projected_current_amount) as q3_value
        FROM deal_phases dp
        JOIN deals d ON d.id = dp.deal_id
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE d.date_start >= CURRENT_DATE - INTERVAL '{years} years'
        GROUP BY dp.stage
        ORDER BY
            CASE dp.stage
                WHEN 'Discovery' THEN 1
                WHEN 'Preclinical' THEN 2
                WHEN 'Phase 1 Clinical' THEN 3
                WHEN 'Phase 2 Clinical' THEN 4
                WHEN 'Phase 3 Clinical' THEN 5
                WHEN 'Pre-registration' THEN 6
                WHEN 'Registered' THEN 7
                WHEN 'Launched' THEN 8
                ELSE 9
            END
    """

    with get_cortellis_session() as session:
        result = session.execute(text(query))

        benchmarks = [
            ValuationBenchmark(
                category=row.phase,
                deal_count=row.deal_count,
                disclosed_count=row.disclosed_count,
                min_value=float(row.min_value) if row.min_value is not None else None,
                max_value=float(row.max_value) if row.max_value is not None else None,
                avg_value=float(row.avg_value) if row.avg_value is not None else None,
                median_value=float(row.median_value) if row.median_value is not None else None,
                q1_value=float(row.q1_value) if row.q1_value is not None else None,
                q3_value=float(row.q3_value) if row.q3_value is not None else None,
            )
            for row in result
        ]

    return ValuationBenchmarksResponse(
        benchmark_type="phase",
        benchmarks=benchmarks,
    )


@router.get("/analytics/valuations/by-indication", response_model=ValuationBenchmarksResponse)
async def get_valuations_by_indication(
    limit: int = Query(20, ge=1, le=50),
    years: int = Query(5, ge=1, le=20),
    min_deals: int = Query(5, ge=1, description="Minimum deals to include indication"),
):
    """
    Get valuation benchmarks by indication.

    Shows deal value statistics for each indication,
    sorted by deal count.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Getting valuations by indication")

    query = f"""
        SELECT
            i.name as indication,
            COUNT(*) as deal_count,
            COUNT(f.total_projected_current_amount) as disclosed_count,
            MIN(f.total_projected_current_amount) as min_value,
            MAX(f.total_projected_current_amount) as max_value,
            AVG(f.total_projected_current_amount) as avg_value,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.total_projected_current_amount) as median_value,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY f.total_projected_current_amount) as q1_value,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY f.total_projected_current_amount) as q3_value
        FROM deal_indications di
        JOIN deals d ON d.id = di.deal_id
        JOIN indications i ON i.id = di.indication_id
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE d.date_start >= CURRENT_DATE - INTERVAL '{years} years'
        GROUP BY i.name
        HAVING COUNT(*) >= :min_deals
        ORDER BY deal_count DESC
        LIMIT :limit
    """

    with get_cortellis_session() as session:
        result = session.execute(text(query), {"limit": limit, "min_deals": min_deals})

        benchmarks = [
            ValuationBenchmark(
                category=row.indication,
                deal_count=row.deal_count,
                disclosed_count=row.disclosed_count,
                min_value=float(row.min_value) if row.min_value is not None else None,
                max_value=float(row.max_value) if row.max_value is not None else None,
                avg_value=float(row.avg_value) if row.avg_value is not None else None,
                median_value=float(row.median_value) if row.median_value is not None else None,
                q1_value=float(row.q1_value) if row.q1_value is not None else None,
                q3_value=float(row.q3_value) if row.q3_value is not None else None,
            )
            for row in result
        ]

    return ValuationBenchmarksResponse(
        benchmark_type="indication",
        benchmarks=benchmarks,
    )


@router.get("/analytics/valuations/by-deal-type", response_model=ValuationBenchmarksResponse)
async def get_valuations_by_deal_type(
    years: int = Query(5, ge=1, le=20),
):
    """
    Get valuation benchmarks by deal type.

    Shows deal value statistics for each deal type
    (License, M&A, Co-development, etc.).
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Getting valuations by deal type")

    query = f"""
        SELECT
            COALESCE(NULLIF(d.deal_type, ''), 'Unspecified') as deal_type,
            COUNT(*) as deal_count,
            COUNT(f.total_projected_current_amount) as disclosed_count,
            MIN(f.total_projected_current_amount) as min_value,
            MAX(f.total_projected_current_amount) as max_value,
            AVG(f.total_projected_current_amount) as avg_value,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.total_projected_current_amount) as median_value,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY f.total_projected_current_amount) as q1_value,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY f.total_projected_current_amount) as q3_value
        FROM deals d
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE d.date_start >= CURRENT_DATE - INTERVAL '{years} years'
        GROUP BY COALESCE(NULLIF(d.deal_type, ''), 'Unspecified')
        ORDER BY deal_count DESC
    """

    with get_cortellis_session() as session:
        result = session.execute(text(query))

        benchmarks = [
            ValuationBenchmark(
                category=row.deal_type,
                deal_count=row.deal_count,
                disclosed_count=row.disclosed_count,
                min_value=float(row.min_value) if row.min_value is not None else None,
                max_value=float(row.max_value) if row.max_value is not None else None,
                avg_value=float(row.avg_value) if row.avg_value is not None else None,
                median_value=float(row.median_value) if row.median_value is not None else None,
                q1_value=float(row.q1_value) if row.q1_value is not None else None,
                q3_value=float(row.q3_value) if row.q3_value is not None else None,
            )
            for row in result
        ]

    return ValuationBenchmarksResponse(
        benchmark_type="deal_type",
        benchmarks=benchmarks,
    )


@router.get("/analytics/top-deals")
async def get_top_deals(
    therapy_area: Optional[str] = None,
    indication: Optional[str] = None,
    deal_type: Optional[str] = None,
    years: int = Query(5, ge=1, le=20),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Get top deals by value.

    Returns the largest deals by total value,
    with optional filtering by therapy area, indication, or deal type.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Getting top deals")

    conditions = [
        "f.total_projected_current_amount IS NOT NULL",
        f"d.date_start >= CURRENT_DATE - INTERVAL '{years} years'",
    ]
    params = {"limit": limit}

    if therapy_area:
        conditions.append("""
            d.id IN (
                SELECT di.deal_id FROM deal_indications di
                JOIN indications i ON i.id = di.indication_id
                WHERE i.name ILIKE :therapy_area
            )
        """)
        params["therapy_area"] = f"%{therapy_area}%"

    if indication:
        conditions.append("""
            d.id IN (
                SELECT di.deal_id FROM deal_indications di
                JOIN indications i ON i.id = di.indication_id
                WHERE i.name ILIKE :indication
            )
        """)
        params["indication"] = f"%{indication}%"

    if deal_type:
        conditions.append("d.deal_type ILIKE :deal_type")
        params["deal_type"] = f"%{deal_type}%"

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            d.id,
            d.title,
            f.total_projected_current_amount as total_value,
            d.date_start::text,
            d.deal_type,
            (SELECT c.name FROM deal_companies dc
             JOIN companies c ON c.id = dc.company_id
             WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal,
            (SELECT c.name FROM deal_companies dc
             JOIN companies c ON c.id = dc.company_id
             WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner
        FROM deals d
        JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE {where_clause}
        ORDER BY f.total_projected_current_amount DESC
        LIMIT :limit
    """

    with get_cortellis_session() as session:
        result = session.execute(text(query), params)

        deals = [
            TopDeal(
                id=row.id,
                title=row.title or "Untitled",
                total_value=float(row.total_value),
                date_start=row.date_start,
                deal_type=row.deal_type,
                principal_company=row.principal,
                partner_company=row.partner,
            )
            for row in result
        ]

    return {
        "deals": [d.model_dump() for d in deals],
        "count": len(deals),
        "filters": {
            "therapy_area": therapy_area,
            "indication": indication,
            "deal_type": deal_type,
            "years": years,
        },
    }


@router.get("/analytics/top-acquirers")
async def get_top_acquirers(
    therapy_area: Optional[str] = None,
    indication: Optional[str] = None,
    years: int = Query(5, ge=1, le=20),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Get most active acquirers/licensees.

    Returns companies with the most deals as partner (acquiring/licensing in),
    with optional filtering.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Getting top acquirers")

    conditions = [
        "dc.role = 'Partner'",
        f"d.date_start >= CURRENT_DATE - INTERVAL '{years} years'",
    ]
    params = {"limit": limit}

    if therapy_area:
        conditions.append("""
            d.id IN (
                SELECT di.deal_id FROM deal_indications di
                JOIN indications i ON i.id = di.indication_id
                WHERE i.name ILIKE :therapy_area
            )
        """)
        params["therapy_area"] = f"%{therapy_area}%"

    if indication:
        conditions.append("""
            d.id IN (
                SELECT di.deal_id FROM deal_indications di
                JOIN indications i ON i.id = di.indication_id
                WHERE i.name ILIKE :indication
            )
        """)
        params["indication"] = f"%{indication}%"

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            c.id,
            c.name,
            c.company_type,
            COUNT(DISTINCT dc.deal_id) as deal_count,
            SUM(f.total_projected_current_amount) as total_value,
            AVG(f.total_projected_current_amount) as avg_value,
            COUNT(f.total_projected_current_amount) as disclosed_count
        FROM deal_companies dc
        JOIN companies c ON c.id = dc.company_id
        JOIN deals d ON d.id = dc.deal_id
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE {where_clause}
        GROUP BY c.id, c.name, c.company_type
        ORDER BY deal_count DESC
        LIMIT :limit
    """

    with get_cortellis_session() as session:
        result = session.execute(text(query), params)

        acquirers = [
            {
                "id": row.id,
                "name": row.name,
                "company_type": row.company_type,
                "deal_count": row.deal_count,
                "total_value": float(row.total_value) if row.total_value is not None else None,
                "avg_value": float(row.avg_value) if row.avg_value is not None else None,
                "disclosed_count": row.disclosed_count,
            }
            for row in result
        ]

    return {
        "acquirers": acquirers,
        "count": len(acquirers),
    }


@router.get("/analytics/deal-activity-summary")
async def get_deal_activity_summary():
    """
    Get overall deal activity summary.

    Returns high-level statistics about the deal database.
    Cached for 30 minutes.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session
    from unified_api.services.cache import cache_get, cache_set, cache_key, TTL_STATS

    logger.info("Getting deal activity summary")

    # Check cache
    key = cache_key("deal_activity_summary")
    cached = cache_get(key)
    if cached:
        return cached

    with get_cortellis_session() as session:
        # Total deals
        total_deals = session.execute(text("SELECT COUNT(*) FROM deals")).scalar()

        # Deals with disclosed values
        disclosed_deals = session.execute(text("""
            SELECT COUNT(*) FROM deal_finance_summary
            WHERE total_projected_current_amount IS NOT NULL
              AND total_projected_current_currency = 'USD'
              AND total_projected_current_unit = 'Million'
        """)).scalar()

        # Total companies
        total_companies = session.execute(text("SELECT COUNT(*) FROM companies")).scalar()

        # Total drugs
        total_drugs = session.execute(text("SELECT COUNT(*) FROM drugs")).scalar()

        # Total indications
        total_indications = session.execute(text("SELECT COUNT(*) FROM indications")).scalar()

        # Deals this year
        deals_this_year = session.execute(text("""
            SELECT COUNT(*) FROM deals
            WHERE EXTRACT(YEAR FROM date_start) = EXTRACT(YEAR FROM CURRENT_DATE)
        """)).scalar()

        # Deals last year
        deals_last_year = session.execute(text("""
            SELECT COUNT(*) FROM deals
            WHERE EXTRACT(YEAR FROM date_start) = EXTRACT(YEAR FROM CURRENT_DATE) - 1
        """)).scalar()

        # Total contract chunks
        total_chunks = session.execute(text("SELECT COUNT(*) FROM contract_chunks")).scalar()

        # Chunks with embeddings
        embedded_chunks = session.execute(text("""
            SELECT COUNT(*) FROM contract_chunks WHERE embedding IS NOT NULL
        """)).scalar()

    result = {
        "deals": {
            "total": total_deals,
            "with_disclosed_value": disclosed_deals,
            "disclosure_rate": round(disclosed_deals / total_deals * 100, 1) if total_deals else 0,
            "this_year": deals_this_year,
            "last_year": deals_last_year,
        },
        "entities": {
            "companies": total_companies,
            "drugs": total_drugs,
            "indications": total_indications,
        },
        "contracts": {
            "total_chunks": total_chunks,
            "embedded_chunks": embedded_chunks,
            "embedding_coverage": round(embedded_chunks / total_chunks * 100, 1) if total_chunks else 0,
        },
    }

    cache_set(key, result, TTL_STATS)
    return result


# ============================================
# Geographic Distribution
# ============================================

@router.get("/analytics/geographic-distribution")
async def get_geographic_distribution(
    years: int = Query(5, ge=1, le=20),
    agreement_type: Optional[str] = None,
    therapy_area: Optional[str] = None,
    limit: int = Query(30, ge=1, le=100),
):
    """
    Get deal distribution by geographic territory.

    Returns deal counts and values by territory,
    useful for geographic heatmap visualizations.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Getting geographic distribution")

    conditions = [f"d.date_start >= CURRENT_DATE - INTERVAL '{years} years'"]
    params = {"limit": limit}

    if agreement_type:
        conditions.append("d.agreement_type ILIKE :agreement_type")
        params["agreement_type"] = f"%{agreement_type}%"

    if therapy_area:
        conditions.append("ta.name ILIKE :therapy_area")
        params["therapy_area"] = f"%{therapy_area}%"

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            t.id as territory_code,
            t.name as territory_name,
            COUNT(DISTINCT dt.deal_id) as deal_count,
            SUM(f.total_projected_current_amount) as total_value,
            AVG(f.total_projected_current_amount) as avg_value,
            COUNT(f.total_projected_current_amount) as disclosed_count
        FROM deal_territories dt
        JOIN territories t ON t.id = dt.territory_id
        JOIN deals d ON d.id = dt.deal_id
        LEFT JOIN therapy_areas ta ON ta.id = d.therapy_area_id
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE {where_clause}
        GROUP BY t.id, t.name
        ORDER BY deal_count DESC
        LIMIT :limit
    """

    with get_cortellis_session() as session:
        result = session.execute(text(query), params)

        territories = [
            {
                "territory_code": row.territory_code,
                "territory_name": row.territory_name,
                "deal_count": row.deal_count,
                "total_value": float(row.total_value) if row.total_value is not None else None,
                "avg_value": float(row.avg_value) if row.avg_value is not None else None,
                "disclosed_count": row.disclosed_count,
            }
            for row in result
        ]

    return {"territories": territories, "count": len(territories)}


# ============================================
# Agreement Type Distribution
# ============================================

@router.get("/analytics/agreement-type-distribution")
async def get_agreement_type_distribution(
    years: int = Query(5, ge=1, le=20),
    therapy_area: Optional[str] = None,
):
    """
    Get deal distribution by agreement type.

    Returns deal counts/values for each of the 21 agreement types,
    grouped by category (Company, Drug, Patent, Technology).
    Ideal for pie/donut charts and treemaps.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Getting agreement type distribution")

    conditions = [
        "d.agreement_type IS NOT NULL",
        f"d.date_start >= CURRENT_DATE - INTERVAL '{years} years'",
    ]
    params = {}

    if therapy_area:
        conditions.append("ta.name ILIKE :therapy_area")
        params["therapy_area"] = f"%{therapy_area}%"

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            d.agreement_type,
            SPLIT_PART(d.agreement_type, ' - ', 1) as category,
            COUNT(*) as deal_count,
            SUM(f.total_projected_current_amount) as total_value,
            AVG(f.total_projected_current_amount) as avg_value,
            COUNT(f.total_projected_current_amount) as disclosed_count
        FROM deals d
        LEFT JOIN therapy_areas ta ON ta.id = d.therapy_area_id
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE {where_clause}
        GROUP BY d.agreement_type
        ORDER BY deal_count DESC
    """

    with get_cortellis_session() as session:
        result = session.execute(text(query), params)

        types = []
        categories = {}
        for row in result:
            entry = {
                "agreement_type": row.agreement_type,
                "category": row.category,
                "deal_count": row.deal_count,
                "total_value": float(row.total_value) if row.total_value is not None else None,
                "avg_value": float(row.avg_value) if row.avg_value is not None else None,
                "disclosed_count": row.disclosed_count,
            }
            types.append(entry)

            cat = row.category
            if cat not in categories:
                categories[cat] = {"deal_count": 0, "total_value": 0}
            categories[cat]["deal_count"] += row.deal_count
            if row.total_value is not None:
                categories[cat]["total_value"] += float(row.total_value)

    return {
        "agreement_types": types,
        "by_category": categories,
        "total_types": len(types),
    }


# ============================================
# Deal Status Funnel
# ============================================

@router.get("/analytics/deal-status-funnel")
async def get_deal_status_funnel(
    years: int = Query(5, ge=1, le=20),
    agreement_type: Optional[str] = None,
):
    """
    Get deal counts by status for funnel visualization.

    Statuses: Pending → Active → Completed / Terminated
    Also returns status transitions over time (quarterly).
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Getting deal status funnel")

    conditions = [f"d.date_start >= CURRENT_DATE - INTERVAL '{years} years'"]
    params = {}

    if agreement_type:
        conditions.append("d.agreement_type ILIKE :agreement_type")
        params["agreement_type"] = f"%{agreement_type}%"

    where_clause = " AND ".join(conditions)

    # Overall status distribution
    status_query = f"""
        SELECT
            d.status,
            COUNT(*) as deal_count,
            SUM(f.total_projected_current_amount) as total_value,
            COUNT(f.total_projected_current_amount) as disclosed_count
        FROM deals d
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE {where_clause}
        GROUP BY d.status
        ORDER BY
            CASE d.status
                WHEN 'Pending' THEN 1
                WHEN 'Active' THEN 2
                WHEN 'Completed' THEN 3
                WHEN 'Terminated' THEN 4
            END
    """

    # Status by year
    timeline_query = f"""
        SELECT
            EXTRACT(YEAR FROM d.date_start)::int as year,
            d.status,
            COUNT(*) as deal_count
        FROM deals d
        WHERE {where_clause}
        GROUP BY EXTRACT(YEAR FROM d.date_start)::int, d.status
        ORDER BY year DESC, d.status
    """

    with get_cortellis_session() as session:
        status_result = session.execute(text(status_query), params)
        funnel = [
            {
                "status": row.status or "Unknown",
                "deal_count": row.deal_count,
                "total_value": float(row.total_value) if row.total_value is not None else None,
                "disclosed_count": row.disclosed_count,
            }
            for row in status_result
        ]

        timeline_result = session.execute(text(timeline_query), params)
        timeline = {}
        for row in timeline_result:
            yr = str(row.year)
            if yr not in timeline:
                timeline[yr] = {}
            timeline[yr][row.status or "Unknown"] = row.deal_count

    return {"funnel": funnel, "by_year": timeline}


# ============================================
# Therapy Area Heatmap
# ============================================

@router.get("/analytics/therapy-area-heatmap")
async def get_therapy_area_heatmap(
    years: int = Query(10, ge=1, le=20),
    limit: int = Query(15, ge=5, le=30, description="Top N therapy areas"),
):
    """
    Get deal activity heatmap by therapy area over time.

    Returns a matrix of therapy areas x years with deal counts
    and values, ideal for heatmap visualization.
    Cached for 1 hour.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session
    from unified_api.services.cache import cache_get, cache_set, cache_key, TTL_ANALYTICS

    logger.info("Getting therapy area heatmap")

    key = cache_key("therapy_heatmap", years=years, limit=limit)
    cached = cache_get(key)
    if cached:
        return cached

    query = f"""
        SELECT
            ta.name as therapy_area,
            EXTRACT(YEAR FROM d.date_start)::int as year,
            COUNT(*) as deal_count,
            SUM(f.total_projected_current_amount) as total_value,
            COUNT(f.total_projected_current_amount) as disclosed_count
        FROM deals d
        JOIN therapy_areas ta ON ta.id = d.therapy_area_id
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE d.date_start >= CURRENT_DATE - INTERVAL '{years} years'
          AND ta.name NOT IN ('Not Applicable', 'Unknown')
        GROUP BY ta.name, EXTRACT(YEAR FROM d.date_start)::int
        ORDER BY ta.name, year
    """

    with get_cortellis_session() as session:
        result = session.execute(text(query))

        # Build heatmap data
        ta_totals = {}
        heatmap = {}
        all_years = set()

        for row in result:
            ta = row.therapy_area
            yr = row.year
            all_years.add(yr)

            if ta not in ta_totals:
                ta_totals[ta] = 0
            ta_totals[ta] += row.deal_count

            if ta not in heatmap:
                heatmap[ta] = {}
            heatmap[ta][yr] = {
                "deal_count": row.deal_count,
                "total_value": float(row.total_value) if row.total_value else 0,
                "disclosed_count": row.disclosed_count,
            }

        # Top N therapy areas by total deal count
        top_areas = sorted(ta_totals.keys(), key=lambda x: ta_totals[x], reverse=True)[:limit]
        sorted_years = sorted(all_years)

        # Build matrix
        matrix = []
        for ta in top_areas:
            row_data = {
                "therapy_area": ta,
                "total_deals": ta_totals[ta],
                "years": {},
            }
            for yr in sorted_years:
                row_data["years"][str(yr)] = heatmap.get(ta, {}).get(yr, {"deal_count": 0, "total_value": 0, "disclosed_count": 0})
            matrix.append(row_data)

    result = {
        "matrix": matrix,
        "years": [str(y) for y in sorted_years],
        "therapy_areas": top_areas,
    }
    cache_set(key, result, TTL_ANALYTICS)
    return result


# ============================================
# M&A Analytics
# ============================================

@router.get("/analytics/ma-analytics")
async def get_ma_analytics(
    years: int = Query(10, ge=1, le=20),
    limit: int = Query(30, ge=1, le=100),
):
    """
    Get M&A-specific analytics.

    Includes acquisition premiums, share price impact,
    and deal size distribution for M&A transactions.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Getting M&A analytics")

    # Overall M&A stats
    stats_query = f"""
        SELECT
            COUNT(*) as total_ma_deals,
            COUNT(f.total_projected_current_amount) as disclosed_count,
            SUM(f.total_projected_current_amount) as total_value,
            AVG(f.total_projected_current_amount) as avg_value,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY f.total_projected_current_amount) as median_value
        FROM deals d
        JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE d.agreement_type = 'Company - M&A (in whole or part)'
          AND d.date_start >= CURRENT_DATE - INTERVAL '{years} years'
          AND f.total_projected_current_amount IS NOT NULL
    """

    # M&A with price-per-share and closing price data (premium analysis)
    premium_query = f"""
        SELECT
            d.id,
            d.title,
            d.date_start::text,
            f.total_projected_current_amount as deal_value,
            ma.price_per_share,
            ma.closing_price_day_one,
            ma.closing_price_day_five,
            ma.closing_price_day_thirty,
            ma.cash_at_acquisition,
            ma.total_revenue_year_prior,
            ma.attitude,
            ma.ownership,
            (SELECT c.name FROM deal_companies dc
             JOIN companies c ON c.id = dc.company_id
             WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as target,
            (SELECT c.name FROM deal_companies dc
             JOIN companies c ON c.id = dc.company_id
             WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as acquirer
        FROM deals d
        JOIN deal_ma_summary ma ON ma.deal_id = d.id
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE d.agreement_type = 'Company - M&A (in whole or part)'
          AND d.date_start >= CURRENT_DATE - INTERVAL '{years} years'
          AND (ma.price_per_share IS NOT NULL OR f.total_projected_current_amount IS NOT NULL)
        ORDER BY f.total_projected_current_amount DESC NULLS LAST
        LIMIT :limit
    """

    # M&A by year
    yearly_query = f"""
        SELECT
            EXTRACT(YEAR FROM d.date_start)::int as year,
            COUNT(*) as deal_count,
            SUM(f.total_projected_current_amount) as total_value,
            AVG(f.total_projected_current_amount) as avg_value,
            COUNT(f.total_projected_current_amount) as disclosed_count
        FROM deals d
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE d.agreement_type = 'Company - M&A (in whole or part)'
          AND d.date_start >= CURRENT_DATE - INTERVAL '{years} years'
        GROUP BY EXTRACT(YEAR FROM d.date_start)::int
        ORDER BY year DESC
    """

    # Attitude breakdown (Friendly vs Hostile)
    attitude_query = f"""
        SELECT
            COALESCE(ma.attitude, 'Not Specified') as attitude,
            COUNT(*) as deal_count,
            AVG(f.total_projected_current_amount) as avg_value
        FROM deals d
        JOIN deal_ma_summary ma ON ma.deal_id = d.id
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE d.agreement_type = 'Company - M&A (in whole or part)'
          AND d.date_start >= CURRENT_DATE - INTERVAL '{years} years'
        GROUP BY COALESCE(ma.attitude, 'Not Specified')
        ORDER BY deal_count DESC
    """

    with get_cortellis_session() as session:
        stats = session.execute(text(stats_query)).fetchone()

        premium_result = session.execute(text(premium_query), {"limit": limit})
        top_deals = []
        for row in premium_result:
            deal = {
                "id": row.id,
                "title": row.title,
                "date_start": row.date_start,
                "deal_value": float(row.deal_value) if row.deal_value is not None else None,
                "target": row.target,
                "acquirer": row.acquirer,
                "price_per_share": float(row.price_per_share) if row.price_per_share is not None else None,
                "attitude": row.attitude,
                "ownership": row.ownership,
            }
            # Calculate share price impact if data available
            if row.closing_price_day_one and row.price_per_share:
                deal["day1_premium_pct"] = round(
                    (row.price_per_share - row.closing_price_day_one) / row.closing_price_day_one * 100, 1
                )
            if row.closing_price_day_thirty and row.price_per_share:
                deal["day30_premium_pct"] = round(
                    (row.price_per_share - row.closing_price_day_thirty) / row.closing_price_day_thirty * 100, 1
                )
            # Revenue multiple
            if row.deal_value and row.total_revenue_year_prior and row.total_revenue_year_prior > 0:
                deal["revenue_multiple"] = round(row.deal_value / row.total_revenue_year_prior, 1)

            top_deals.append(deal)

        yearly_result = session.execute(text(yearly_query))
        yearly = [
            {
                "year": row.year,
                "deal_count": row.deal_count,
                "total_value": float(row.total_value) if row.total_value is not None else None,
                "avg_value": float(row.avg_value) if row.avg_value is not None else None,
                "disclosed_count": row.disclosed_count,
            }
            for row in yearly_result
        ]

        attitude_result = session.execute(text(attitude_query))
        attitudes = [
            {
                "attitude": row.attitude,
                "deal_count": row.deal_count,
                "avg_value": float(row.avg_value) if row.avg_value is not None else None,
            }
            for row in attitude_result
        ]

    return {
        "summary": {
            "total_ma_deals": stats.total_ma_deals if stats else 0,
            "disclosed_count": stats.disclosed_count if stats else 0,
            "total_value": float(stats.total_value) if stats and stats.total_value is not None else None,
            "avg_value": float(stats.avg_value) if stats and stats.avg_value is not None else None,
            "median_value": float(stats.median_value) if stats and stats.median_value is not None else None,
        },
        "top_deals": top_deals,
        "by_year": yearly,
        "by_attitude": attitudes,
    }


# ============================================
# Company Comparison
# ============================================

@router.get("/analytics/company-comparison")
async def get_company_comparison(
    company_ids: str = Query(..., description="Comma-separated company IDs (2-5)"),
    years: int = Query(5, ge=1, le=20),
):
    """
    Compare deal activity across multiple companies.

    Provides side-by-side metrics for 2-5 companies including
    deal counts, values, top indications, and partner diversity.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    ids = [int(x.strip()) for x in company_ids.split(",") if x.strip().isdigit()][:5]

    if len(ids) < 2:
        return {"error": "Provide at least 2 company IDs"}

    logger.info("Comparing companies", company_ids=ids)

    query = f"""
        SELECT
            c.id,
            c.name,
            c.company_type,
            dc.role,
            COUNT(DISTINCT dc.deal_id) as deal_count,
            SUM(f.total_projected_current_amount) as total_value,
            AVG(f.total_projected_current_amount) as avg_value,
            COUNT(f.total_projected_current_amount) as disclosed_count,
            COUNT(DISTINCT EXTRACT(YEAR FROM d.date_start)) as active_years
        FROM deal_companies dc
        JOIN companies c ON c.id = dc.company_id
        JOIN deals d ON d.id = dc.deal_id
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE c.id = ANY(:ids)
          AND d.date_start >= CURRENT_DATE - INTERVAL '{years} years'
        GROUP BY c.id, c.name, c.company_type, dc.role
        ORDER BY c.id, deal_count DESC
    """

    # Top indications per company
    indication_query = f"""
        SELECT
            dc.company_id,
            i.name as indication,
            COUNT(*) as deal_count
        FROM deal_companies dc
        JOIN deals d ON d.id = dc.deal_id
        JOIN deal_indications di ON di.deal_id = d.id
        JOIN indications i ON i.id = di.indication_id
        WHERE dc.company_id = ANY(:ids)
          AND d.date_start >= CURRENT_DATE - INTERVAL '{years} years'
        GROUP BY dc.company_id, i.name
        ORDER BY dc.company_id, deal_count DESC
    """

    # Partner count per company
    partner_query = f"""
        SELECT
            dc1.company_id,
            COUNT(DISTINCT dc2.company_id) as unique_partners
        FROM deal_companies dc1
        JOIN deal_companies dc2 ON dc2.deal_id = dc1.deal_id AND dc2.company_id <> dc1.company_id
        JOIN deals d ON d.id = dc1.deal_id
        WHERE dc1.company_id = ANY(:ids)
          AND d.date_start >= CURRENT_DATE - INTERVAL '{years} years'
        GROUP BY dc1.company_id
    """

    # Yearly trend per company
    trend_query = f"""
        SELECT
            dc.company_id,
            EXTRACT(YEAR FROM d.date_start)::int as year,
            COUNT(*) as deal_count,
            SUM(f.total_projected_current_amount) as total_value
        FROM deal_companies dc
        JOIN deals d ON d.id = dc.deal_id
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE dc.company_id = ANY(:ids)
          AND d.date_start >= CURRENT_DATE - INTERVAL '{years} years'
        GROUP BY dc.company_id, EXTRACT(YEAR FROM d.date_start)::int
        ORDER BY dc.company_id, year
    """

    with get_cortellis_session() as session:
        params = {"ids": ids}

        # Main metrics
        result = session.execute(text(query), params)
        companies = {}
        for row in result:
            cid = row.id
            if cid not in companies:
                companies[cid] = {
                    "id": cid,
                    "name": row.name,
                    "company_type": row.company_type,
                    "by_role": {},
                    "total_deals": 0,
                    "total_value": 0,
                }
            companies[cid]["by_role"][row.role] = {
                "deal_count": row.deal_count,
                "total_value": float(row.total_value) if row.total_value is not None else None,
                "avg_value": float(row.avg_value) if row.avg_value is not None else None,
                "disclosed_count": row.disclosed_count,
            }
            companies[cid]["total_deals"] += row.deal_count
            if row.total_value is not None:
                companies[cid]["total_value"] += float(row.total_value)

        # Indications
        ind_result = session.execute(text(indication_query), params)
        ind_by_company = {}
        for row in ind_result:
            cid = row.company_id
            if cid not in ind_by_company:
                ind_by_company[cid] = []
            if len(ind_by_company[cid]) < 5:
                ind_by_company[cid].append({"indication": row.indication, "deal_count": row.deal_count})

        for cid in companies:
            companies[cid]["top_indications"] = ind_by_company.get(cid, [])

        # Partners
        partner_result = session.execute(text(partner_query), params)
        for row in partner_result:
            if row.company_id in companies:
                companies[row.company_id]["unique_partners"] = row.unique_partners

        # Trends
        trend_result = session.execute(text(trend_query), params)
        for row in trend_result:
            cid = row.company_id
            if cid in companies:
                if "yearly_trend" not in companies[cid]:
                    companies[cid]["yearly_trend"] = []
                companies[cid]["yearly_trend"].append({
                    "year": row.year,
                    "deal_count": row.deal_count,
                    "total_value": float(row.total_value) if row.total_value is not None else None,
                })

    return {"companies": list(companies.values())}


# ============================================
# Year-over-Year Growth
# ============================================

@router.get("/analytics/yoy-growth")
async def get_yoy_growth(
    years: int = Query(10, ge=2, le=20),
    therapy_area: Optional[str] = None,
):
    """
    Get year-over-year growth metrics.

    Returns deal count, total value, and avg value with
    YoY percentage changes for each year.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Getting YoY growth")

    conditions = [
        "d.date_start IS NOT NULL",
        f"d.date_start >= CURRENT_DATE - INTERVAL '{years} years'",
    ]
    params = {}

    if therapy_area:
        conditions.append("ta.name ILIKE :therapy_area")
        params["therapy_area"] = f"%{therapy_area}%"

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            EXTRACT(YEAR FROM d.date_start)::int as year,
            COUNT(*) as deal_count,
            SUM(f.total_projected_current_amount) as total_value,
            AVG(f.total_projected_current_amount) as avg_value,
            COUNT(f.total_projected_current_amount) as disclosed_count
        FROM deals d
        LEFT JOIN therapy_areas ta ON ta.id = d.therapy_area_id
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
          AND f.total_projected_current_currency = 'USD'
          AND f.total_projected_current_unit = 'Million'
        WHERE {where_clause}
        GROUP BY EXTRACT(YEAR FROM d.date_start)::int
        ORDER BY year ASC
    """

    with get_cortellis_session() as session:
        result = session.execute(text(query), params)
        rows = list(result)

    # Calculate YoY changes
    data = []
    prev = None
    for row in rows:
        entry = {
            "year": row.year,
            "deal_count": row.deal_count,
            "total_value": float(row.total_value) if row.total_value is not None else None,
            "avg_value": float(row.avg_value) if row.avg_value is not None else None,
            "disclosed_count": row.disclosed_count,
        }

        if prev:
            if prev["deal_count"] > 0:
                entry["deal_count_growth_pct"] = round(
                    (row.deal_count - prev["deal_count"]) / prev["deal_count"] * 100, 1
                )
            if prev.get("total_value") and entry.get("total_value"):
                entry["value_growth_pct"] = round(
                    (entry["total_value"] - prev["total_value"]) / prev["total_value"] * 100, 1
                )

        data.append(entry)
        prev = entry

    return {"data": data, "years_covered": len(data)}


# ============================================
# Cache Management
# ============================================

@router.post("/analytics/cache/invalidate")
async def invalidate_analytics_cache():
    """
    Invalidate all analytics caches.

    Call after data syncs to ensure fresh results.
    """
    from unified_api.services.cache import cache_invalidate

    deleted = cache_invalidate("bd:*")
    logger.info("Analytics cache invalidated", keys_deleted=deleted)
    return {"success": True, "keys_deleted": deleted}
