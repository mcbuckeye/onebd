"""
Entity Resolution / Cross-Reference endpoints.

Manages company identity linking across Cortellis and Edgar BD databases.
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Path
from pydantic import BaseModel
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()


class CompanySearchResult(BaseModel):
    """A company search result."""
    id: int
    name: str
    company_type: Optional[str] = None
    ticker: Optional[str] = None
    cik: Optional[str] = None
    similarity: float = 0
    has_xref: bool = False


class XrefData(BaseModel):
    """Cross-reference data for a company."""
    xref_id: int
    cortellis_id: int
    cik: Optional[str] = None
    ticker: Optional[str] = None
    canonical_name: str
    match_method: str
    match_confidence: float
    manually_verified: bool
    name: str
    company_type: Optional[str] = None
    hq_location: Optional[str] = None


class MatchRequest(BaseModel):
    """Request to find a match for an external company."""
    name: str
    ticker: Optional[str] = None
    cik: Optional[str] = None
    min_similarity: float = 0.6


class MatchResult(BaseModel):
    """Result of a company match attempt."""
    found: bool
    cortellis_id: Optional[int] = None
    cortellis_name: Optional[str] = None
    match_method: Optional[str] = None
    confidence: Optional[float] = None
    ticker: Optional[str] = None
    cik: Optional[str] = None


class CreateXrefRequest(BaseModel):
    """Request to create or update a cross-reference."""
    cortellis_id: int
    cik: Optional[str] = None
    ticker: Optional[str] = None
    verified: bool = False
    verified_by: Optional[str] = None


class XrefStats(BaseModel):
    """Statistics about entity resolution."""
    companies: dict
    xrefs: dict
    by_method: dict
    avg_confidence: float


@router.get("/xref/search", response_model=List[CompanySearchResult])
async def search_companies(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Search Cortellis companies by name.

    Uses fuzzy matching (trigram similarity) to find companies.
    Returns companies sorted by relevance with xref status.
    """
    from unified_api.services.entity_resolution import get_entity_resolution_service

    logger.info("Searching companies", query=q)

    service = get_entity_resolution_service()
    results = service.search_companies(q, limit=limit)

    return [CompanySearchResult(**r) for r in results]


@router.get("/xref/company/{company_id}", response_model=Optional[XrefData])
async def get_company_xref(company_id: int = Path(..., gt=0)):
    """
    Get cross-reference data for a Cortellis company.

    Returns CIK, ticker, and match metadata if available.
    """
    from unified_api.services.entity_resolution import get_entity_resolution_service

    logger.info("Getting company xref", company_id=company_id)

    service = get_entity_resolution_service()
    xref = service.get_unified_company(cortellis_id=company_id)

    if not xref:
        return None

    return XrefData(**xref)


@router.get("/xref/lookup")
async def lookup_by_identifier(
    cik: Optional[str] = Query(None, description="SEC CIK number"),
    ticker: Optional[str] = Query(None, description="Stock ticker symbol"),
):
    """
    Look up a company by CIK or ticker.

    Returns the unified company record if found.
    """
    if not cik and not ticker:
        raise HTTPException(
            status_code=400,
            detail="Must provide either cik or ticker"
        )

    from unified_api.services.entity_resolution import get_entity_resolution_service

    logger.info("Looking up by identifier", cik=cik, ticker=ticker)

    service = get_entity_resolution_service()
    xref = service.get_unified_company(cik=cik, ticker=ticker)

    if not xref:
        return {"found": False, "cik": cik, "ticker": ticker}

    return {"found": True, **xref}


@router.post("/xref/match", response_model=MatchResult)
async def find_match(request: MatchRequest):
    """
    Find the best Cortellis match for an external company.

    Matching priority:
    1. CIK (exact match, 100% confidence)
    2. Ticker (exact match, 100% confidence)
    3. Name (exact or fuzzy match)

    Use this endpoint to resolve companies from Edgar BD or other sources.
    """
    from unified_api.services.entity_resolution import get_entity_resolution_service

    logger.info(
        "Finding match",
        name=request.name,
        ticker=request.ticker,
        cik=request.cik,
    )

    service = get_entity_resolution_service()
    match = service.find_cortellis_match(
        name=request.name,
        ticker=request.ticker,
        cik=request.cik,
        min_similarity=request.min_similarity,
    )

    if not match:
        return MatchResult(found=False)

    return MatchResult(
        found=True,
        cortellis_id=match.cortellis_id,
        cortellis_name=match.cortellis_name,
        match_method=match.match_method,
        confidence=match.match_confidence,
        ticker=match.ticker,
        cik=match.cik,
    )


@router.post("/xref/create")
async def create_xref(request: CreateXrefRequest):
    """
    Create or update a cross-reference entry.

    Links a Cortellis company to CIK and/or ticker.
    Also updates the companies table with these identifiers.
    """
    from unified_api.services.entity_resolution import get_entity_resolution_service

    logger.info(
        "Creating xref",
        cortellis_id=request.cortellis_id,
        cik=request.cik,
        ticker=request.ticker,
    )

    service = get_entity_resolution_service()

    try:
        xref_id = service.create_xref(
            cortellis_id=request.cortellis_id,
            cik=request.cik,
            ticker=request.ticker,
            match_method="manual" if request.verified else "api",
            confidence=1.0 if request.verified else 0.9,
            verified=request.verified,
            verified_by=request.verified_by,
        )

        return {
            "success": True,
            "xref_id": xref_id,
            "cortellis_id": request.cortellis_id,
        }

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Failed to create xref", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/xref/stats", response_model=XrefStats)
async def get_stats():
    """
    Get entity resolution statistics.

    Returns counts of:
    - Total companies and those with CIK/ticker
    - Cross-references by match method
    - Average match confidence
    """
    from unified_api.services.entity_resolution import get_entity_resolution_service

    service = get_entity_resolution_service()
    stats = service.get_matching_stats()

    return XrefStats(**stats)


class AutoMatchResult(BaseModel):
    """Result of automatic entity resolution."""
    edgar_unmatched_checked: int
    new_ticker_matches: int
    new_trigram_matches: int
    failed_to_match: int
    new_xrefs_created: int


@router.post("/xref/auto-match", response_model=AutoMatchResult)
async def auto_match_edgar_companies(
    min_similarity: float = Query(0.6, ge=0.3, le=1.0, description="Minimum trigram similarity threshold"),
):
    """
    Automatically match unmatched Edgar SEC filer companies to Cortellis.

    This endpoint:
    1. Finds Edgar companies with CIK that are NOT yet in company_xref
    2. Matches them to Cortellis by ticker (exact) or name (trigram fuzzy)
    3. Creates new xref entries for successful matches

    Use this to populate company_xref with Edgar → Cortellis links.
    """
    from unified_api.services.entity_resolution import get_entity_resolution_service

    logger.info("Starting automatic entity resolution", min_similarity=min_similarity)

    service = get_entity_resolution_service()
    stats = service.match_unmatched_edgar_companies(min_similarity=min_similarity)

    logger.info("Automatic entity resolution completed", **stats)

    return AutoMatchResult(**stats)


@router.post("/xref/batch-match")
async def batch_match(
    companies: List[MatchRequest],
    auto_create: bool = Query(True, description="Auto-create xref entries for matches"),
):
    """
    Match a batch of external companies to Cortellis.

    Useful for bulk entity resolution from Edgar BD or other sources.
    Returns match statistics and individual results.
    """
    from unified_api.services.entity_resolution import get_entity_resolution_service

    logger.info("Batch matching", count=len(companies))

    service = get_entity_resolution_service()

    results = {
        "total": len(companies),
        "matched": 0,
        "unmatched": 0,
        "matches": [],
        "unmatched_companies": [],
    }

    for company in companies:
        match = service.find_cortellis_match(
            name=company.name,
            ticker=company.ticker,
            cik=company.cik,
            min_similarity=company.min_similarity,
        )

        if match:
            results["matched"] += 1
            results["matches"].append({
                "input": company.model_dump(),
                "match": {
                    "cortellis_id": match.cortellis_id,
                    "cortellis_name": match.cortellis_name,
                    "method": match.match_method,
                    "confidence": match.match_confidence,
                }
            })

            # Auto-create xref if requested
            if auto_create and (company.cik or company.ticker):
                try:
                    service.create_xref(
                        cortellis_id=match.cortellis_id,
                        cik=company.cik,
                        ticker=company.ticker,
                        match_method=match.match_method,
                        confidence=match.match_confidence,
                    )
                except Exception as e:
                    logger.warning(
                        "Failed to create xref",
                        cortellis_id=match.cortellis_id,
                        error=str(e),
                    )
        else:
            results["unmatched"] += 1
            results["unmatched_companies"].append(company.model_dump())

    return results


# ============================================
# Company Deduplication
# ============================================

@router.get("/xref/duplicates")
async def find_duplicate_companies(
    min_similarity: float = Query(0.85, ge=0.5, le=1.0, description="Trigram similarity threshold"),
    limit: int = Query(50, ge=1, le=200),
):
    """
    Find potential duplicate companies using trigram similarity.

    Returns pairs of companies that likely represent the same entity,
    along with their deal counts to help prioritize merges.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Finding duplicate companies", threshold=min_similarity)

    with get_cortellis_session() as session:
        # Set trigram similarity threshold for the session
        session.execute(text(f"SET pg_trgm.similarity_threshold = {min_similarity}"))

        # Find duplicates among companies that have at least 1 deal
        # Uses GIN index on name with % operator for trigram matching
        result = session.execute(text("""
            SELECT
                c1.id as id_a, c1.name as name_a, c1.company_type as type_a,
                c1.ticker as ticker_a, c1.cik as cik_a,
                c2.id as id_b, c2.name as name_b, c2.company_type as type_b,
                c2.ticker as ticker_b, c2.cik as cik_b,
                similarity(c1.name, c2.name) as sim,
                (SELECT COUNT(*) FROM deal_companies dc WHERE dc.company_id = c1.id) as deals_a,
                (SELECT COUNT(*) FROM deal_companies dc WHERE dc.company_id = c2.id) as deals_b
            FROM companies c1
            JOIN companies c2 ON c1.id < c2.id AND c1.name % c2.name
            WHERE EXISTS (SELECT 1 FROM deal_companies dc WHERE dc.company_id = c1.id)
              AND EXISTS (SELECT 1 FROM deal_companies dc WHERE dc.company_id = c2.id)
            ORDER BY sim DESC
            LIMIT :limit
        """), {"limit": limit})

        duplicates = [
            {
                "company_a": {
                    "id": row.id_a,
                    "name": row.name_a,
                    "company_type": row.type_a,
                    "ticker": row.ticker_a,
                    "cik": row.cik_a,
                    "deal_count": row.deals_a,
                },
                "company_b": {
                    "id": row.id_b,
                    "name": row.name_b,
                    "company_type": row.type_b,
                    "ticker": row.ticker_b,
                    "cik": row.cik_b,
                    "deal_count": row.deals_b,
                },
                "similarity": round(float(row.sim), 3),
            }
            for row in result
        ]

    return {"duplicates": duplicates, "count": len(duplicates), "threshold": min_similarity}


@router.post("/xref/merge-companies")
async def merge_companies(
    keep_id: int = Query(..., description="Company ID to keep (primary)"),
    merge_id: int = Query(..., description="Company ID to merge into primary"),
):
    """
    Merge two duplicate companies.

    Reassigns all deals, notes, and relationships from merge_id to keep_id,
    then deletes the merged company.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    if keep_id == merge_id:
        raise HTTPException(status_code=400, detail="Cannot merge a company with itself")

    logger.info("Merging companies", keep_id=keep_id, merge_id=merge_id)

    with get_cortellis_session() as session:
        # Verify both exist
        keep = session.execute(text(
            "SELECT id, name FROM companies WHERE id = :id"
        ), {"id": keep_id}).fetchone()
        merge = session.execute(text(
            "SELECT id, name FROM companies WHERE id = :id"
        ), {"id": merge_id}).fetchone()

        if not keep:
            raise HTTPException(status_code=404, detail=f"Company {keep_id} not found")
        if not merge:
            raise HTTPException(status_code=404, detail=f"Company {merge_id} not found")

        # Count deals being moved
        merge_deals = session.execute(text(
            "SELECT COUNT(*) FROM deal_companies WHERE company_id = :id"
        ), {"id": merge_id}).scalar()

        # Reassign deal_companies (avoid duplicates by using ON CONFLICT)
        session.execute(text("""
            UPDATE deal_companies
            SET company_id = :keep_id
            WHERE company_id = :merge_id
              AND deal_id NOT IN (
                  SELECT deal_id FROM deal_companies WHERE company_id = :keep_id
              )
        """), {"keep_id": keep_id, "merge_id": merge_id})

        # Delete remaining deal_companies for merge_id (were duplicates)
        session.execute(text(
            "DELETE FROM deal_companies WHERE company_id = :merge_id"
        ), {"merge_id": merge_id})

        # Update company_xref if exists
        session.execute(text("""
            UPDATE company_xref SET cortellis_id = :keep_id
            WHERE cortellis_id = :merge_id
        """), {"keep_id": keep_id, "merge_id": merge_id})

        # Copy over any useful fields from merged company
        # (e.g., if keep has no ticker but merge does)
        session.execute(text("""
            UPDATE companies SET
                ticker = COALESCE(
                    (SELECT ticker FROM companies WHERE id = :keep_id),
                    (SELECT ticker FROM companies WHERE id = :merge_id)
                ),
                cik = COALESCE(
                    (SELECT cik FROM companies WHERE id = :keep_id),
                    (SELECT cik FROM companies WHERE id = :merge_id)
                ),
                company_type = COALESCE(
                    NULLIF((SELECT company_type FROM companies WHERE id = :keep_id), ''),
                    (SELECT company_type FROM companies WHERE id = :merge_id)
                )
            WHERE id = :keep_id
        """), {"keep_id": keep_id, "merge_id": merge_id})

        # Delete the merged company
        session.execute(text(
            "DELETE FROM companies WHERE id = :merge_id"
        ), {"merge_id": merge_id})

        session.commit()

    return {
        "success": True,
        "kept": {"id": keep_id, "name": keep.name},
        "merged": {"id": merge_id, "name": merge.name},
        "deals_moved": merge_deals,
    }
