"""
Search endpoints for deals, companies, and documents.
"""
from typing import Optional, List
from fastapi import APIRouter, Query
from pydantic import BaseModel
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()


class DealSummary(BaseModel):
    """Summary of a deal for search results."""
    id: int
    title: str
    deal_type: Optional[str] = None
    status: Optional[str] = None
    date_start: Optional[str] = None
    total_value: Optional[float] = None
    principal_company: Optional[str] = None
    partner_company: Optional[str] = None
    principal_company_id: Optional[int] = None
    partner_company_id: Optional[int] = None


class SearchFilters(BaseModel):
    """Filters for deal search."""
    therapy_area: Optional[str] = None
    indication: Optional[List[str]] = None
    technology: Optional[List[str]] = None
    company: Optional[str] = None
    deal_type: Optional[List[str]] = None
    phase: Optional[List[str]] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    value_min: Optional[float] = None
    value_max: Optional[float] = None
    disclosed_only: bool = False
    status: Optional[List[str]] = None


class SearchResponse(BaseModel):
    """Response from deal search."""
    total: int
    page: int
    page_size: int
    results: List[DealSummary]


@router.post("/search/deals", response_model=SearchResponse)
async def search_deals(
    filters: SearchFilters,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort_by: str = Query("date_start", enum=["date_start", "total_value", "title"]),
    sort_order: str = Query("desc", enum=["asc", "desc"]),
):
    """
    Search deals with multi-criteria filtering.

    Supports filtering by:
    - Therapy area (e.g., Oncology)
    - Indication (multiple)
    - Technology/modality
    - Company (principal or partner)
    - Deal type
    - Development phase
    - Date range
    - Value range
    - Disclosed values only
    - Status
    """
    logger.info(
        "Searching deals",
        filters=filters.model_dump(exclude_none=True),
        page=page,
        page_size=page_size,
    )

    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    # Build query with filters
    conditions = []
    params = {"limit": page_size, "offset": (page - 1) * page_size}
    joins = []

    # Company filter
    if filters.company:
        conditions.append("""
            d.id IN (
                SELECT dc.deal_id FROM deal_companies dc
                JOIN companies c ON c.id = dc.company_id
                WHERE c.name ILIKE :company_search
            )
        """)
        params["company_search"] = f"%{filters.company}%"

    # Deal type filter (using agreement_type which has actual values)
    if filters.deal_type:
        conditions.append("d.agreement_type = ANY(:deal_types)")
        params["deal_types"] = filters.deal_type

    # Date range filters
    if filters.date_from:
        conditions.append("d.date_start >= :date_from")
        params["date_from"] = filters.date_from

    if filters.date_to:
        conditions.append("d.date_start <= :date_to")
        params["date_to"] = filters.date_to

    # Therapy area filter
    if filters.therapy_area:
        joins.append("LEFT JOIN therapy_areas ta ON ta.id = d.therapy_area_id")
        conditions.append("ta.name ILIKE :therapy_area")
        params["therapy_area"] = f"%{filters.therapy_area}%"

    # Indication filter
    if filters.indication:
        conditions.append("""
            d.id IN (
                SELECT di.deal_id FROM deal_indications di
                JOIN indications i ON i.id = di.indication_id
                WHERE i.name ILIKE ANY(:indications)
            )
        """)
        params["indications"] = [f"%{ind}%" for ind in filters.indication]

    # Technology filter
    if filters.technology:
        conditions.append("""
            d.id IN (
                SELECT dt.deal_id FROM deal_technologies dt
                JOIN technologies t ON t.id = dt.technology_id
                WHERE t.name ILIKE ANY(:technologies)
            )
        """)
        params["technologies"] = [f"%{tech}%" for tech in filters.technology]

    # Phase filter
    if filters.phase:
        conditions.append("d.phase_highest_start = ANY(:phases)")
        params["phases"] = filters.phase

    # Value range filters
    if filters.value_min is not None:
        conditions.append("f.total_projected_current_amount >= :value_min")
        params["value_min"] = filters.value_min

    if filters.value_max is not None:
        conditions.append("f.total_projected_current_amount <= :value_max")
        params["value_max"] = filters.value_max

    # Disclosed only filter
    if filters.disclosed_only:
        conditions.append("f.total_projected_current_amount IS NOT NULL")

    # Status filter
    if filters.status:
        conditions.append("d.status = ANY(:statuses)")
        params["statuses"] = filters.status

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    join_clause = " ".join(joins)

    # Sort mapping
    sort_col = {
        "date_start": "d.date_start",
        "total_value": "f.total_projected_current_amount",
        "title": "d.title",
    }.get(sort_by, "d.date_start")

    query = f"""
        SELECT
            d.id,
            d.title,
            d.deal_type,
            d.status,
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
        {join_clause}
        WHERE {where_clause}
        ORDER BY {sort_col} {sort_order.upper()} NULLS LAST
        LIMIT :limit OFFSET :offset
    """

    count_query = f"""
        SELECT COUNT(DISTINCT d.id) FROM deals d
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
        {join_clause}
        WHERE {where_clause}
    """

    with get_cortellis_session() as session:
        # Get total count
        total = session.execute(text(count_query), params).scalar()

        # Get results
        result = session.execute(text(query), params)
        results = [
            DealSummary(
                id=row.id,
                title=row.title or "Untitled",
                deal_type=row.deal_type,
                status=row.status,
                date_start=row.date_start,
                total_value=row.total_value,
                principal_company=row.principal,
                partner_company=row.partner,
                principal_company_id=row.principal_id,
                partner_company_id=row.partner_id,
            )
            for row in result
        ]

        return SearchResponse(
            total=total,
            page=page,
            page_size=page_size,
            results=results,
        )


class FilterOptions(BaseModel):
    """Available filter options for deal search."""
    therapy_areas: List[str] = []
    deal_types: List[str] = []
    statuses: List[str] = []
    phases: List[str] = []


@router.get("/search/filters", response_model=FilterOptions)
async def get_filter_options():
    """
    Get available filter options for deal search.

    Returns lists of:
    - Therapy areas
    - Deal types
    - Deal statuses
    - Development phases
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Getting filter options")

    with get_cortellis_session() as session:
        # Get therapy areas
        ta_result = session.execute(text("""
            SELECT DISTINCT name FROM therapy_areas
            WHERE name IS NOT NULL AND name != ''
            ORDER BY name
        """))
        therapy_areas = [row.name for row in ta_result]

        # Get deal types (using agreement_type which has actual values)
        dt_result = session.execute(text("""
            SELECT DISTINCT agreement_type FROM deals
            WHERE agreement_type IS NOT NULL AND agreement_type != ''
            ORDER BY agreement_type
        """))
        deal_types = [row.agreement_type for row in dt_result]

        # Get statuses
        status_result = session.execute(text("""
            SELECT DISTINCT status FROM deals
            WHERE status IS NOT NULL AND status != ''
            ORDER BY status
        """))
        statuses = [row.status for row in status_result]

        # Get phases
        phase_result = session.execute(text("""
            SELECT DISTINCT phase_highest_start FROM deals
            WHERE phase_highest_start IS NOT NULL AND phase_highest_start != ''
            ORDER BY phase_highest_start
        """))
        phases = [row.phase_highest_start for row in phase_result]

        return FilterOptions(
            therapy_areas=therapy_areas,
            deal_types=deal_types,
            statuses=statuses,
            phases=phases,
        )


class ContractSearchResult(BaseModel):
    """A contract search result."""
    chunk_id: int
    deal_id: int
    deal_title: Optional[str] = None
    contract_id: int
    content: str
    score: float
    principal_company: Optional[str] = None
    partner_company: Optional[str] = None
    principal_company_id: Optional[int] = None
    partner_company_id: Optional[int] = None


@router.get("/search/contracts")
async def search_contracts(
    query: str = Query(..., min_length=3),
    mode: str = Query("semantic", enum=["fulltext", "semantic", "hybrid"]),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Search contract documents using RAG.

    Modes:
    - **fulltext**: PostgreSQL full-text search on contract content
    - **semantic**: pgvector cosine similarity using embeddings
    - **hybrid**: Combined fulltext + semantic with reranking
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session
    from unified_api.services.embed import get_embedding_provider

    logger.info(
        "Searching contracts",
        query=query,
        mode=mode,
        limit=limit,
    )

    results = []

    with get_cortellis_session() as session:
        if mode in ["semantic", "hybrid"]:
            # Generate embedding for query
            try:
                embedding_provider = get_embedding_provider()
                query_embedding = await embedding_provider.embed_single(query)

                # Convert to PostgreSQL array format
                embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

                # Semantic search using pgvector
                # Note: Use CAST() instead of :: to avoid SQLAlchemy parameter binding conflict
                semantic_result = session.execute(text("""
                    SELECT
                        cc.id as chunk_id,
                        cc.deal_id,
                        cc.contract_id,
                        cc.content,
                        1 - (cc.embedding <=> CAST(:embedding AS vector)) as similarity,
                        d.title as deal_title,
                        (SELECT c.name FROM deal_companies dc
                         JOIN companies c ON c.id = dc.company_id
                         WHERE dc.deal_id = cc.deal_id AND dc.role = 'Principal' LIMIT 1) as principal,
                        (SELECT c.id FROM deal_companies dc
                         JOIN companies c ON c.id = dc.company_id
                         WHERE dc.deal_id = cc.deal_id AND dc.role = 'Principal' LIMIT 1) as principal_id,
                        (SELECT c.name FROM deal_companies dc
                         JOIN companies c ON c.id = dc.company_id
                         WHERE dc.deal_id = cc.deal_id AND dc.role = 'Partner' LIMIT 1) as partner,
                        (SELECT c.id FROM deal_companies dc
                         JOIN companies c ON c.id = dc.company_id
                         WHERE dc.deal_id = cc.deal_id AND dc.role = 'Partner' LIMIT 1) as partner_id
                    FROM contract_chunks cc
                    JOIN deals d ON d.id = cc.deal_id
                    WHERE cc.embedding IS NOT NULL
                    ORDER BY cc.embedding <=> CAST(:embedding AS vector)
                    LIMIT :limit
                """), {"embedding": embedding_str, "limit": limit})

                for row in semantic_result:
                    results.append(ContractSearchResult(
                        chunk_id=row.chunk_id,
                        deal_id=row.deal_id,
                        deal_title=row.deal_title,
                        contract_id=row.contract_id,
                        content=row.content[:500] + "..." if len(row.content) > 500 else row.content,
                        score=float(row.similarity),
                        principal_company=row.principal,
                        partner_company=row.partner,
                        principal_company_id=row.principal_id,
                        partner_company_id=row.partner_id,
                    ))

            except Exception as e:
                logger.error("Semantic search failed", error=str(e))
                # Fall back to fulltext if semantic fails
                if mode == "semantic":
                    return {"query": query, "mode": mode, "results": [], "error": str(e)}

        if mode in ["fulltext", "hybrid"] and (mode == "fulltext" or not results):
            # Fulltext search using PostgreSQL
            fulltext_result = session.execute(text("""
                SELECT
                    cc.id as chunk_id,
                    cc.deal_id,
                    cc.contract_id,
                    cc.content,
                    ts_rank(to_tsvector('english', cc.content), plainto_tsquery('english', :query)) as rank,
                    d.title as deal_title,
                    (SELECT c.name FROM deal_companies dc
                     JOIN companies c ON c.id = dc.company_id
                     WHERE dc.deal_id = cc.deal_id AND dc.role = 'Principal' LIMIT 1) as principal,
                    (SELECT c.id FROM deal_companies dc
                     JOIN companies c ON c.id = dc.company_id
                     WHERE dc.deal_id = cc.deal_id AND dc.role = 'Principal' LIMIT 1) as principal_id,
                    (SELECT c.name FROM deal_companies dc
                     JOIN companies c ON c.id = dc.company_id
                     WHERE dc.deal_id = cc.deal_id AND dc.role = 'Partner' LIMIT 1) as partner,
                    (SELECT c.id FROM deal_companies dc
                     JOIN companies c ON c.id = dc.company_id
                     WHERE dc.deal_id = cc.deal_id AND dc.role = 'Partner' LIMIT 1) as partner_id
                FROM contract_chunks cc
                JOIN deals d ON d.id = cc.deal_id
                WHERE to_tsvector('english', cc.content) @@ plainto_tsquery('english', :query)
                ORDER BY rank DESC
                LIMIT :limit
            """), {"query": query, "limit": limit})

            for row in fulltext_result:
                results.append(ContractSearchResult(
                    chunk_id=row.chunk_id,
                    deal_id=row.deal_id,
                    deal_title=row.deal_title,
                    contract_id=row.contract_id,
                    content=row.content[:500] + "..." if len(row.content) > 500 else row.content,
                    score=float(row.rank),
                principal_company=row.principal,
                    partner_company=row.partner,
                    principal_company_id=row.principal_id,
                    partner_company_id=row.partner_id,
                ))

    return {
        "query": query,
        "mode": mode,
        "total": len(results),
        "results": [r.model_dump() for r in results],
    }


class UnifiedSearchResult(BaseModel):
    """A unified search result from any source."""
    source: str  # 'cortellis' or 'edgar'
    chunk_id: int
    document_id: Optional[int] = None
    content: str
    score: float
    # Cortellis fields
    deal_id: Optional[int] = None
    deal_title: Optional[str] = None
    contract_id: Optional[int] = None
    principal_company: Optional[str] = None
    partner_company: Optional[str] = None
    principal_company_id: Optional[int] = None
    partner_company_id: Optional[int] = None
    # Edgar fields
    doc_type: Optional[str] = None
    accession_no: Optional[str] = None
    filing_date: Optional[str] = None
    company_name: Optional[str] = None
    company_ticker: Optional[str] = None


@router.get("/search/unified")
async def unified_search(
    query: str = Query(..., min_length=3),
    sources: str = Query("both", enum=["cortellis", "edgar", "both"]),
    mode: str = Query("fulltext", enum=["fulltext", "semantic"]),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Unified search across both Cortellis contracts and Edgar SEC filings.

    Searches across 4.2M+ document chunks from both sources:
    - **Cortellis**: 903K contract chunks from pharmaceutical deals
    - **Edgar**: 3.3M SEC filing chunks (10-K, 8-K, exhibits)

    Modes:
    - **fulltext**: PostgreSQL full-text search
    - **semantic**: pgvector cosine similarity (requires embeddings)

    Sources:
    - **cortellis**: Only Cortellis contracts
    - **edgar**: Only SEC filings
    - **both**: Combined results (default)
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session, get_edgar_session

    logger.info(
        "Unified search",
        query=query,
        sources=sources,
        mode=mode,
        limit=limit,
    )

    results = []
    per_source_limit = limit if sources != "both" else limit // 2 + 5

    # Search Cortellis contracts
    if sources in ["cortellis", "both"]:
        try:
            with get_cortellis_session() as session:
                if mode == "fulltext":
                    cortellis_result = session.execute(text("""
                        SELECT
                            cc.id as chunk_id,
                            cc.deal_id,
                            cc.contract_id,
                            cc.content,
                            ts_rank(to_tsvector('english', cc.content), plainto_tsquery('english', :query)) as score,
                            d.title as deal_title,
                            (SELECT c.name FROM deal_companies dc
                             JOIN companies c ON c.id = dc.company_id
                             WHERE dc.deal_id = cc.deal_id AND dc.role = 'Principal' LIMIT 1) as principal,
                            (SELECT c.id FROM deal_companies dc
                             JOIN companies c ON c.id = dc.company_id
                             WHERE dc.deal_id = cc.deal_id AND dc.role = 'Principal' LIMIT 1) as principal_id,
                            (SELECT c.name FROM deal_companies dc
                             JOIN companies c ON c.id = dc.company_id
                             WHERE dc.deal_id = cc.deal_id AND dc.role = 'Partner' LIMIT 1) as partner,
                            (SELECT c.id FROM deal_companies dc
                             JOIN companies c ON c.id = dc.company_id
                             WHERE dc.deal_id = cc.deal_id AND dc.role = 'Partner' LIMIT 1) as partner_id
                        FROM contract_chunks cc
                        JOIN deals d ON d.id = cc.deal_id
                        WHERE to_tsvector('english', cc.content) @@ plainto_tsquery('english', :query)
                        ORDER BY score DESC
                        LIMIT :limit
                    """), {"query": query, "limit": per_source_limit})

                    for row in cortellis_result:
                        results.append(UnifiedSearchResult(
                            source="cortellis",
                            chunk_id=row.chunk_id,
                            deal_id=row.deal_id,
                            contract_id=row.contract_id,
                            content=row.content[:500] + "..." if len(row.content) > 500 else row.content,
                            score=float(row.score),
                            deal_title=row.deal_title,
                            principal_company=row.principal,
                            partner_company=row.partner,
                            principal_company_id=row.principal_id,
                            partner_company_id=row.partner_id,
                        ))
        except Exception as e:
            logger.error("Cortellis search failed", error=str(e))

    # Search Edgar SEC filings (use source database directly for index access)
    if sources in ["edgar", "both"]:
        try:
            from unified_api.services.database import get_edgar_source_session

            with get_edgar_source_session() as session:
                if mode == "fulltext":
                    # Query source database tables directly (has the GIN index)
                    edgar_result = session.execute(text("""
                        SELECT
                            c.id as chunk_id,
                            c.document_id,
                            c.text as content,
                            ts_rank(to_tsvector('english', c.text), plainto_tsquery('english', :query)) as score,
                            d.doc_type,
                            d.accession_no,
                            r.filing_date,
                            e.name as company_name,
                            e.ticker
                        FROM chunks c
                        JOIN documents d ON c.document_id = d.id
                        JOIN raw_documents r ON d.raw_document_id = r.id
                        JOIN companies e ON r.company_id = e.id
                        WHERE to_tsvector('english', c.text) @@ plainto_tsquery('english', :query)
                        ORDER BY score DESC
                        LIMIT :limit
                    """), {"query": query, "limit": per_source_limit})

                    for row in edgar_result:
                        results.append(UnifiedSearchResult(
                            source="edgar",
                            chunk_id=row.chunk_id,
                            document_id=row.document_id,
                            content=row.content[:500] + "..." if len(row.content) > 500 else row.content,
                            score=float(row.score),
                            doc_type=row.doc_type,
                            accession_no=row.accession_no,
                            filing_date=str(row.filing_date) if row.filing_date else None,
                            company_name=row.company_name,
                            company_ticker=row.ticker,
                        ))
        except Exception as e:
            logger.error("Edgar search failed", error=str(e))

    # Sort combined results by score and limit
    results.sort(key=lambda x: x.score, reverse=True)
    results = results[:limit]

    return {
        "query": query,
        "mode": mode,
        "sources": sources,
        "total": len(results),
        "results": [r.model_dump() for r in results],
    }


# ============================================
# Autocomplete Endpoints
# ============================================

@router.get("/search/autocomplete/companies")
async def autocomplete_companies(
    q: str = Query(..., min_length=2, description="Search prefix"),
    limit: int = Query(10, ge=1, le=50),
):
    """
    Typeahead autocomplete for company names.

    Uses trigram similarity for fuzzy matching.
    Results cached for 2 hours.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session
    from unified_api.services.cache import cache_get, cache_set, cache_key, TTL_AUTOCOMPLETE

    key = cache_key("ac_company", q=q.lower(), limit=limit)
    cached = cache_get(key)
    if cached:
        return cached

    with get_cortellis_session() as session:
        result = session.execute(text("""
            SELECT id, name, company_type, ticker,
                   similarity(name, :query) as sim
            FROM companies
            WHERE name ILIKE :prefix OR name % :query
            ORDER BY
                CASE WHEN name ILIKE :exact_prefix THEN 0 ELSE 1 END,
                sim DESC
            LIMIT :limit
        """), {
            "query": q,
            "prefix": f"%{q}%",
            "exact_prefix": f"{q}%",
            "limit": limit,
        })

        suggestions = [
            {
                "id": row.id,
                "name": row.name,
                "company_type": row.company_type,
                "ticker": row.ticker,
            }
            for row in result
        ]

    response = {"query": q, "suggestions": suggestions}
    cache_set(key, response, TTL_AUTOCOMPLETE)
    return response


@router.get("/search/autocomplete/indications")
async def autocomplete_indications(
    q: str = Query(..., min_length=2, description="Search prefix"),
    limit: int = Query(10, ge=1, le=50),
):
    """
    Typeahead autocomplete for indication names.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session
    from unified_api.services.cache import cache_get, cache_set, cache_key, TTL_AUTOCOMPLETE

    key = cache_key("ac_indication", q=q.lower(), limit=limit)
    cached = cache_get(key)
    if cached:
        return cached

    with get_cortellis_session() as session:
        result = session.execute(text("""
            SELECT i.id, i.name,
                   COUNT(di.deal_id) as deal_count
            FROM indications i
            LEFT JOIN deal_indications di ON di.indication_id = i.id
            WHERE i.name ILIKE :prefix
            GROUP BY i.id, i.name
            ORDER BY
                CASE WHEN i.name ILIKE :exact_prefix THEN 0 ELSE 1 END,
                deal_count DESC
            LIMIT :limit
        """), {
            "prefix": f"%{q}%",
            "exact_prefix": f"{q}%",
            "limit": limit,
        })

        suggestions = [
            {"id": row.id, "name": row.name, "deal_count": row.deal_count}
            for row in result
        ]

    response = {"query": q, "suggestions": suggestions}
    cache_set(key, response, TTL_AUTOCOMPLETE)
    return response


@router.get("/search/autocomplete/drugs")
async def autocomplete_drugs(
    q: str = Query(..., min_length=2, description="Search prefix"),
    limit: int = Query(10, ge=1, le=50),
):
    """
    Typeahead autocomplete for drug names.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session
    from unified_api.services.cache import cache_get, cache_set, cache_key, TTL_AUTOCOMPLETE

    key = cache_key("ac_drug", q=q.lower(), limit=limit)
    cached = cache_get(key)
    if cached:
        return cached

    with get_cortellis_session() as session:
        result = session.execute(text("""
            SELECT dr.id, dr.name_display as name, dr.phase_highest_now as phase,
                   COUNT(dd.deal_id) as deal_count
            FROM drugs dr
            LEFT JOIN deal_drugs dd ON dd.drug_id = dr.id
            WHERE dr.name_display ILIKE :prefix
            GROUP BY dr.id, dr.name_display, dr.phase_highest_now
            ORDER BY
                CASE WHEN dr.name_display ILIKE :exact_prefix THEN 0 ELSE 1 END,
                deal_count DESC
            LIMIT :limit
        """), {
            "prefix": f"%{q}%",
            "exact_prefix": f"{q}%",
            "limit": limit,
        })

        suggestions = [
            {"id": row.id, "name": row.name, "phase": row.phase, "deal_count": row.deal_count}
            for row in result
        ]

    response = {"query": q, "suggestions": suggestions}
    cache_set(key, response, TTL_AUTOCOMPLETE)
    return response


# ============================================
# Search History
# ============================================

@router.post("/search/history")
async def record_search(
    query: str = Query(..., description="Search query text"),
    search_type: str = Query("deals", description="Type of search"),
    result_count: int = Query(0, ge=0),
    user_id: str = Query("default", description="User ID"),
):
    """
    Record a search in history.
    Called by the frontend after executing a search.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    with get_cortellis_session() as session:
        # Ensure table exists
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS search_history (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(100) NOT NULL DEFAULT 'default',
                query TEXT NOT NULL,
                search_type VARCHAR(50) NOT NULL DEFAULT 'deals',
                result_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """))

        session.execute(text("""
            INSERT INTO search_history (user_id, query, search_type, result_count)
            VALUES (:user_id, :query, :search_type, :result_count)
        """), {
            "user_id": user_id,
            "query": query,
            "search_type": search_type,
            "result_count": result_count,
        })
        session.commit()

    return {"success": True}


@router.get("/search/history")
async def get_search_history(
    user_id: str = Query("default", description="User ID"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Get recent search history for a user.

    Returns searches ordered by most recent, with duplicates collapsed
    to show the latest occurrence.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    with get_cortellis_session() as session:
        # Check if table exists
        exists = session.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'search_history'
            )
        """)).scalar()

        if not exists:
            return {"history": [], "total": 0}

        result = session.execute(text("""
            SELECT DISTINCT ON (query, search_type)
                id, query, search_type, result_count, created_at::text
            FROM search_history
            WHERE user_id = :user_id
            ORDER BY query, search_type, created_at DESC
        """), {"user_id": user_id})

        # Re-sort by created_at after dedup
        history = sorted(
            [
                {
                    "id": row.id,
                    "query": row.query,
                    "search_type": row.search_type,
                    "result_count": row.result_count,
                    "created_at": row.created_at,
                }
                for row in result
            ],
            key=lambda x: x["created_at"] or "",
            reverse=True,
        )[:limit]

    return {"history": history, "total": len(history)}


@router.delete("/search/history")
async def clear_search_history(
    user_id: str = Query("default", description="User ID"),
):
    """Clear search history for a user."""
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    with get_cortellis_session() as session:
        exists = session.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'search_history'
            )
        """)).scalar()

        if not exists:
            return {"success": True, "deleted": 0}

        result = session.execute(text("""
            DELETE FROM search_history WHERE user_id = :user_id
        """), {"user_id": user_id})
        session.commit()

    return {"success": True}
