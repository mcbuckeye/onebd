"""
Edgar BD SEC filings endpoints.
Query SEC filings, documents, and perform semantic search across 3.3M+ chunks.
"""
from typing import Optional, List
from datetime import date
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
import structlog

from unified_api.config import settings

logger = structlog.get_logger(__name__)

router = APIRouter()


class EdgarCompanyResponse(BaseModel):
    """Edgar BD company information."""
    id: int
    cik: Optional[str] = None
    ticker: Optional[str] = None
    name: str
    country: Optional[str] = None
    sector: Optional[str] = None
    cortellis_id: Optional[int] = None
    filing_count: int = 0


class EdgarFilingResponse(BaseModel):
    """SEC filing information."""
    id: int
    accession_no: Optional[str] = None
    doc_type: Optional[str] = None
    title: Optional[str] = None
    filing_date: Optional[str] = None
    published_at: Optional[str] = None
    company_name: str
    company_ticker: Optional[str] = None
    url: Optional[str] = None


class EdgarSearchResult(BaseModel):
    """Semantic search result from SEC filings."""
    chunk_id: int
    document_id: int
    section: Optional[str] = None
    text: str
    score: float
    doc_type: Optional[str] = None
    accession_no: Optional[str] = None
    filing_date: Optional[str] = None
    company_name: str
    company_ticker: Optional[str] = None


class EdgarDealResponse(BaseModel):
    """Edgar extracted deal information."""
    id: int
    deal_type: str
    announced_at: Optional[str] = None
    stage: Optional[str] = None
    territory: Optional[str] = None
    description: Optional[str] = None
    status: str
    parties: List[dict] = []
    terms: List[dict] = []


@router.get("/edgar/companies", response_model=List[EdgarCompanyResponse])
async def list_edgar_companies(
    search: Optional[str] = Query(None, description="Search by name or ticker"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    List companies tracked in Edgar BD with SEC filing counts.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_edgar_session

    search_condition = ""
    params = {"limit": limit, "offset": offset}

    if search:
        search_condition = "WHERE e.name ILIKE :search OR e.ticker ILIKE :search OR e.cik LIKE :search_exact"
        params["search"] = f"%{search}%"
        params["search_exact"] = f"%{search}%"

    with get_edgar_session() as session:
        result = session.execute(text(f"""
            SELECT
                e.id, e.cik, e.ticker, e.name, e.country, e.sector,
                (SELECT COUNT(*) FROM raw_documents r WHERE r.company_id = e.id) as filing_count
            FROM companies e
            {search_condition}
            ORDER BY filing_count DESC
            LIMIT :limit OFFSET :offset
        """), params)

        return [
            EdgarCompanyResponse(
                id=row.id,
                cik=row.cik,
                ticker=row.ticker,
                name=row.name,
                country=row.country,
                sector=row.sector,
                cortellis_id=None,  # Lookup via company_xref if needed
                filing_count=row.filing_count,
            )
            for row in result
        ]


@router.get("/edgar/companies/{company_id}", response_model=EdgarCompanyResponse)
async def get_edgar_company(company_id: int):
    """Get details for a specific Edgar company."""
    from sqlalchemy import text
    from unified_api.services.database import get_edgar_session

    with get_edgar_session() as session:
        result = session.execute(text("""
            SELECT
                e.id, e.cik, e.ticker, e.name, e.country, e.sector,
                (SELECT COUNT(*) FROM raw_documents r WHERE r.company_id = e.id) as filing_count
            FROM companies e
            WHERE e.id = :company_id
        """), {"company_id": company_id})

        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Company not found")

        return EdgarCompanyResponse(
            id=row.id,
            cik=row.cik,
            ticker=row.ticker,
            name=row.name,
            country=row.country,
            sector=row.sector,
            cortellis_id=None,  # Lookup via company_xref if needed
            filing_count=row.filing_count,
        )


@router.get("/edgar/companies/{company_id}/filings", response_model=List[EdgarFilingResponse])
async def get_company_filings(
    company_id: int,
    doc_type: Optional[str] = Query(None, description="Filter by doc type (8-K, 10-K, etc.)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Get SEC filings for a specific company."""
    from sqlalchemy import text
    from unified_api.services.database import get_edgar_session

    type_filter = ""
    params = {"company_id": company_id, "limit": limit, "offset": offset}

    if doc_type:
        type_filter = "AND COALESCE(d.subtype, d.doc_type) = :doc_type"
        params["doc_type"] = doc_type

    with get_edgar_session() as session:
        result = session.execute(text(f"""
            SELECT
                d.id, d.accession_no, COALESCE(d.subtype, d.doc_type) AS doc_type,
                d.title, d.published_at,
                r.filing_date, r.url,
                e.name as company_name, e.ticker
            FROM documents d
            JOIN raw_documents r ON d.raw_document_id = r.id
            JOIN companies e ON r.company_id = e.id
            WHERE e.id = :company_id {type_filter}
            ORDER BY d.published_at DESC NULLS LAST
            LIMIT :limit OFFSET :offset
        """), params)

        return [
            EdgarFilingResponse(
                id=row.id,
                accession_no=row.accession_no,
                doc_type=row.doc_type,
                title=row.title,
                filing_date=str(row.filing_date) if row.filing_date else None,
                published_at=str(row.published_at) if row.published_at else None,
                company_name=row.company_name,
                company_ticker=row.ticker,
                url=row.url,
            )
            for row in result
        ]


@router.get("/edgar/filings", response_model=List[EdgarFilingResponse])
async def search_filings(
    search: Optional[str] = Query(None, description="Search in title or accession number"),
    doc_type: Optional[str] = Query(None, description="Filter by doc type"),
    company: Optional[str] = Query(None, description="Filter by company name/ticker"),
    date_from: Optional[date] = Query(None, description="Filing date from"),
    date_to: Optional[date] = Query(None, description="Filing date to"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    Search SEC filings across all companies.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_edgar_session

    conditions = []
    params = {"limit": limit, "offset": offset}

    if search:
        conditions.append("(d.title ILIKE :search OR d.accession_no ILIKE :search)")
        params["search"] = f"%{search}%"

    if doc_type:
        conditions.append("COALESCE(d.subtype, d.doc_type) = :doc_type")
        params["doc_type"] = doc_type

    if company:
        conditions.append("(e.name ILIKE :company OR e.ticker ILIKE :company)")
        params["company"] = f"%{company}%"

    if date_from:
        conditions.append("r.filing_date >= :date_from")
        params["date_from"] = date_from

    if date_to:
        conditions.append("r.filing_date <= :date_to")
        params["date_to"] = date_to

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    with get_edgar_session() as session:
        result = session.execute(text(f"""
            SELECT
                d.id, d.accession_no, COALESCE(d.subtype, d.doc_type) AS doc_type,
                d.title, d.published_at,
                r.filing_date, r.url,
                e.name as company_name, e.ticker
            FROM documents d
            JOIN raw_documents r ON d.raw_document_id = r.id
            JOIN companies e ON r.company_id = e.id
            WHERE {where_clause}
            ORDER BY r.filing_date DESC NULLS LAST
            LIMIT :limit OFFSET :offset
        """), params)

        return [
            EdgarFilingResponse(
                id=row.id,
                accession_no=row.accession_no,
                doc_type=row.doc_type,
                title=row.title,
                filing_date=str(row.filing_date) if row.filing_date else None,
                published_at=str(row.published_at) if row.published_at else None,
                company_name=row.company_name,
                company_ticker=row.ticker,
                url=row.url,
            )
            for row in result
        ]


@router.get("/edgar/filings/{filing_id}")
async def get_filing_detail(filing_id: int):
    """Get detailed information about a specific SEC filing."""
    from sqlalchemy import text
    from unified_api.services.database import get_edgar_session

    with get_edgar_session() as session:
        result = session.execute(text("""
            SELECT
                d.id, d.accession_no, COALESCE(d.subtype, d.doc_type) AS doc_type,
                d.title, d.published_at,
                d.section_path, d.parse_ok,
                r.filing_date, r.url, r.filing_metadata,
                e.id as company_id, e.name as company_name, e.ticker, e.cik,
                (SELECT COUNT(*) FROM chunks c WHERE c.document_id = d.id) as chunk_count
            FROM documents d
            JOIN raw_documents r ON d.raw_document_id = r.id
            JOIN companies e ON r.company_id = e.id
            WHERE d.id = :filing_id
        """), {"filing_id": filing_id})

        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Filing not found")

        return {
            "id": row.id,
            "accession_no": row.accession_no,
            "doc_type": row.doc_type,
            "title": row.title,
            "published_at": str(row.published_at) if row.published_at else None,
            "filing_date": str(row.filing_date) if row.filing_date else None,
            "url": row.url,
            "section_path": row.section_path,
            "parse_ok": row.parse_ok,
            "chunk_count": row.chunk_count,
            "company": {
                "id": row.company_id,
                "name": row.company_name,
                "ticker": row.ticker,
                "cik": row.cik,
            },
        }


@router.get("/edgar/search", response_model=List[EdgarSearchResult])
async def search_edgar_filings(
    query: str = Query(..., min_length=3, description="Search query"),
    mode: str = Query("fulltext", enum=["fulltext", "semantic"]),
    doc_type: Optional[str] = Query(None, description="Filter by doc type"),
    company: Optional[str] = Query(None, description="Filter by company"),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Search SEC filing content using fulltext or semantic search.

    Searches across 3.3M+ document chunks from SEC filings.

    Modes:
    - **fulltext**: PostgreSQL full-text search
    - **semantic**: pgvector cosine similarity (requires embeddings)
    """
    from sqlalchemy import text
    from unified_api.services.database import get_edgar_source_session

    logger.info("Searching Edgar filings", query=query, mode=mode, limit=limit)

    results = []

    # Use source database directly (has the GIN index for fulltext search)
    with get_edgar_source_session() as session:
        if mode == "fulltext":
            # Build conditions
            conditions = ["to_tsvector('english', c.text) @@ plainto_tsquery('english', :query)"]
            params = {
                "query": query,
                "limit": limit,
                "candidate_limit": max(limit, settings.edgar_fulltext_candidate_limit),
            }

            if doc_type:
                conditions.append("COALESCE(d.subtype, d.doc_type) = :doc_type")
                params["doc_type"] = doc_type

            if company:
                conditions.append("(e.name ILIKE :company OR e.ticker ILIKE :company)")
                params["company"] = f"%{company}%"

            where_clause = " AND ".join(conditions)

            # Query source database tables (chunks, documents, raw_documents, companies)
            result = session.execute(text(f"""
                WITH candidates AS MATERIALIZED (
                    SELECT
                        c.id AS chunk_id,
                        c.document_id,
                        c.section,
                        c.text,
                        to_tsvector('english', c.text) AS search_vector,
                        COALESCE(d.subtype, d.doc_type) AS doc_type,
                        d.accession_no,
                        r.filing_date,
                        e.name AS company_name,
                        e.ticker
                    FROM chunks c
                    JOIN documents d ON c.document_id = d.id
                    JOIN raw_documents r ON d.raw_document_id = r.id
                    JOIN companies e ON r.company_id = e.id
                    WHERE {where_clause}
                    LIMIT :candidate_limit
                )
                SELECT
                    chunk_id, document_id, section, text,
                    ts_rank(search_vector, plainto_tsquery('english', :query)) AS score,
                    doc_type, accession_no, filing_date, company_name, ticker
                FROM candidates
                ORDER BY score DESC
                LIMIT :limit
            """), params)

            for row in result:
                results.append(EdgarSearchResult(
                    chunk_id=row.chunk_id,
                    document_id=row.document_id,
                    section=row.section,
                    text=row.text[:500] + "..." if len(row.text) > 500 else row.text,
                    score=float(row.score),
                    doc_type=row.doc_type,
                    accession_no=row.accession_no,
                    filing_date=str(row.filing_date) if row.filing_date else None,
                    company_name=row.company_name,
                    company_ticker=row.ticker,
                ))

        elif mode == "semantic":
            # Semantic search requires embedding the query
            from unified_api.services.embed import get_embedding_provider

            try:
                embedding_provider = get_embedding_provider()
                query_embedding = await embedding_provider.embed_single(query)
                embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
                session.execute(text("SET LOCAL ivfflat.probes = 40"))

                conditions = ["c.vector IS NOT NULL"]
                params = {"embedding": embedding_str, "limit": limit}

                if doc_type:
                    conditions.append("COALESCE(d.subtype, d.doc_type) = :doc_type")
                    params["doc_type"] = doc_type

                if company:
                    conditions.append("(e.name ILIKE :company OR e.ticker ILIKE :company)")
                    params["company"] = f"%{company}%"

                where_clause = " AND ".join(conditions)

                # Query source database tables (has the vector index)
                result = session.execute(text(f"""
                    SELECT
                        c.id as chunk_id,
                        c.document_id,
                        c.section,
                        c.text,
                        1 - (c.vector <=> CAST(:embedding AS vector)) as score,
                        COALESCE(d.subtype, d.doc_type) AS doc_type,
                        d.accession_no,
                        r.filing_date,
                        e.name as company_name,
                        e.ticker
                    FROM chunks c
                    JOIN documents d ON c.document_id = d.id
                    JOIN raw_documents r ON d.raw_document_id = r.id
                    JOIN companies e ON r.company_id = e.id
                    WHERE {where_clause}
                    ORDER BY c.vector <=> CAST(:embedding AS vector)
                    LIMIT :limit
                """), params)

                for row in result:
                    results.append(EdgarSearchResult(
                        chunk_id=row.chunk_id,
                        document_id=row.document_id,
                        section=row.section,
                        text=row.text[:500] + "..." if len(row.text) > 500 else row.text,
                        score=float(row.score),
                        doc_type=row.doc_type,
                        accession_no=row.accession_no,
                        filing_date=str(row.filing_date) if row.filing_date else None,
                        company_name=row.company_name,
                        company_ticker=row.ticker,
                    ))
            except Exception as e:
                logger.error("Semantic search failed", error=str(e))
                raise HTTPException(status_code=500, detail=f"Semantic search failed: {str(e)}")

    return results


@router.get("/edgar/deals", response_model=List[EdgarDealResponse])
async def list_edgar_deals(
    deal_type: Optional[str] = Query(None, description="Filter by deal type"),
    company: Optional[str] = Query(None, description="Filter by company name"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    List deals extracted from SEC filings.

    These are LLM-extracted deals from 8-K and 10-K filings with provenance tracking.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_edgar_session

    conditions = []
    params = {"limit": limit, "offset": offset}

    if deal_type:
        conditions.append("d.deal_type = :deal_type")
        params["deal_type"] = deal_type

    if company:
        conditions.append("""
            d.id IN (
                SELECT dp.deal_id FROM deal_parties dp
                JOIN companies c ON c.id = dp.company_id
                WHERE c.name ILIKE :company
            )
        """)
        params["company"] = f"%{company}%"

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    with get_edgar_session() as session:
        # Get deals
        result = session.execute(text(f"""
            SELECT
                d.id, d.deal_type, d.announced_at, d.stage, d.territory,
                d.description, d.status
            FROM deals d
            WHERE {where_clause}
            ORDER BY d.announced_at DESC NULLS LAST
            LIMIT :limit OFFSET :offset
        """), params)

        deals = []
        for row in result:
            # Get parties for this deal
            parties_result = session.execute(text("""
                SELECT dp.role, c.name, c.ticker, c.cik
                FROM deal_parties dp
                JOIN companies c ON c.id = dp.company_id
                WHERE dp.deal_id = :deal_id
            """), {"deal_id": row.id})

            parties = [
                {"role": p.role, "name": p.name, "ticker": p.ticker, "cik": p.cik}
                for p in parties_result
            ]

            # Get terms for this deal
            terms_result = session.execute(text("""
                SELECT term_type, amount_usd, currency, min_rate, max_rate, notes
                FROM deal_terms
                WHERE deal_id = :deal_id
            """), {"deal_id": row.id})

            terms = [
                {
                    "term_type": t.term_type,
                    "amount_usd": float(t.amount_usd) if t.amount_usd else None,
                    "currency": t.currency,
                    "min_rate": float(t.min_rate) if t.min_rate else None,
                    "max_rate": float(t.max_rate) if t.max_rate else None,
                    "notes": t.notes,
                }
                for t in terms_result
            ]

            deals.append(EdgarDealResponse(
                id=row.id,
                deal_type=row.deal_type,
                announced_at=str(row.announced_at) if row.announced_at else None,
                stage=row.stage,
                territory=row.territory,
                description=row.description[:300] + "..." if row.description and len(row.description) > 300 else row.description,
                status=row.status,
                parties=parties,
                terms=terms,
            ))

        return deals


@router.get("/edgar/deals/{deal_id}")
async def get_edgar_deal_detail(deal_id: int):
    """Get detailed information about an extracted deal including provenance."""
    from sqlalchemy import text
    from unified_api.services.database import get_edgar_session

    with get_edgar_session() as session:
        result = session.execute(text("""
            SELECT
                d.id, d.deal_type, d.announced_at, d.effective_at, d.stage,
                d.territory, d.description, d.status
            FROM deals d
            WHERE d.id = :deal_id
        """), {"deal_id": deal_id})

        row = result.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Deal not found")

        # Get parties
        parties_result = session.execute(text("""
            SELECT dp.role, c.id, c.name, c.ticker, c.cik
            FROM deal_parties dp
            JOIN companies c ON c.id = dp.company_id
            WHERE dp.deal_id = :deal_id
        """), {"deal_id": deal_id})

        parties = [
            {"role": p.role, "company_id": p.id, "name": p.name, "ticker": p.ticker, "cik": p.cik}
            for p in parties_result
        ]

        # Get terms
        terms_result = session.execute(text("""
            SELECT id, term_type, amount_native, amount_usd, currency, min_rate, max_rate, notes
            FROM deal_terms
            WHERE deal_id = :deal_id
        """), {"deal_id": deal_id})

        terms = [
            {
                "id": t.id,
                "term_type": t.term_type,
                "amount_native": float(t.amount_native) if t.amount_native else None,
                "amount_usd": float(t.amount_usd) if t.amount_usd else None,
                "currency": t.currency,
                "min_rate": float(t.min_rate) if t.min_rate else None,
                "max_rate": float(t.max_rate) if t.max_rate else None,
                "notes": t.notes,
            }
            for t in terms_result
        ]

        # Get provenance (source documents)
        prov_result = session.execute(text("""
            SELECT
                p.id, p.quote_text, p.paragraph_id,
                d.id as doc_id, COALESCE(d.subtype, d.doc_type) AS doc_type,
                d.accession_no,
                c.name as company_name
            FROM provenance p
            LEFT JOIN documents d ON p.document_id = d.id
            LEFT JOIN raw_documents r ON d.raw_document_id = r.id
            LEFT JOIN companies c ON r.company_id = c.id
            WHERE p.deal_id = :deal_id
        """), {"deal_id": deal_id})

        provenance = [
            {
                "id": p.id,
                "quote_text": p.quote_text[:500] + "..." if p.quote_text and len(p.quote_text) > 500 else p.quote_text,
                "paragraph_id": p.paragraph_id,
                "document": {
                    "id": p.doc_id,
                    "doc_type": p.doc_type,
                    "accession_no": p.accession_no,
                    "company_name": p.company_name,
                } if p.doc_id else None,
            }
            for p in prov_result
        ]

        # Get assets
        assets_result = session.execute(text("""
            SELECT a.id, a.name, a.modality, a.target
            FROM deal_assets da
            JOIN assets a ON a.id = da.asset_id
            WHERE da.deal_id = :deal_id
        """), {"deal_id": deal_id})

        assets = [
            {"id": a.id, "name": a.name, "modality": a.modality, "target": a.target}
            for a in assets_result
        ]

        # Get indications
        indications_result = session.execute(text("""
            SELECT i.id, i.name, i.disease_area
            FROM deal_indications di
            JOIN indications i ON i.id = di.indication_id
            WHERE di.deal_id = :deal_id
        """), {"deal_id": deal_id})

        indications = [
            {"id": i.id, "name": i.name, "disease_area": i.disease_area}
            for i in indications_result
        ]

        return {
            "id": row.id,
            "deal_type": row.deal_type,
            "announced_at": str(row.announced_at) if row.announced_at else None,
            "effective_at": str(row.effective_at) if row.effective_at else None,
            "stage": row.stage,
            "territory": row.territory,
            "description": row.description,
            "status": row.status,
            "parties": parties,
            "terms": terms,
            "assets": assets,
            "indications": indications,
            "provenance": provenance,
        }


# ============================================
# Filing Viewer Endpoints
# ============================================

@router.get("/edgar/filings/{filing_id}/content")
async def get_filing_content(
    filing_id: int,
    mode: str = Query("full", enum=["full", "chunks"], description="full=doc_text, chunks=paginated chunks"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """
    Get the full text content of a SEC filing.

    Modes:
    - **full**: Returns complete document text from doc_text table
    - **chunks**: Returns paginated chunks with section labels

    This is the core "filing viewer" endpoint for reading SEC documents.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_edgar_source_session

    with get_edgar_source_session() as session:
        # Verify filing exists
        doc = session.execute(text("""
            SELECT d.id, COALESCE(d.subtype, d.doc_type) AS doc_type,
                   d.title, d.accession_no, d.published_at,
                   e.name as company_name, e.ticker, r.url
            FROM documents d
            JOIN raw_documents r ON d.raw_document_id = r.id
            JOIN companies e ON r.company_id = e.id
            WHERE d.id = :filing_id
        """), {"filing_id": filing_id}).fetchone()

        if not doc:
            raise HTTPException(status_code=404, detail="Filing not found")

        filing_meta = {
            "id": doc.id,
            "doc_type": doc.doc_type,
            "title": doc.title,
            "accession_no": doc.accession_no,
            "published_at": str(doc.published_at) if doc.published_at else None,
            "company_name": doc.company_name,
            "company_ticker": doc.ticker,
            "source_url": doc.url,
        }

        if mode == "full":
            # Get full document text
            doc_text = session.execute(text("""
                SELECT text, char_count, lang
                FROM doc_text
                WHERE document_id = :filing_id
            """), {"filing_id": filing_id}).fetchone()

            if doc_text and doc_text.text:
                return {
                    **filing_meta,
                    "content": doc_text.text,
                    "char_count": doc_text.char_count,
                    "language": doc_text.lang,
                }
            else:
                # Fall back to reconstructing from chunks
                chunks = session.execute(text("""
                    SELECT text FROM chunks
                    WHERE document_id = :filing_id
                    ORDER BY chunk_index ASC
                """), {"filing_id": filing_id})
                full_text = "\n\n".join(row.text for row in chunks)
                return {
                    **filing_meta,
                    "content": full_text,
                    "char_count": len(full_text),
                    "source": "reconstructed_from_chunks",
                }

        else:
            # Paginated chunks
            offset = (page - 1) * page_size

            total = session.execute(text("""
                SELECT COUNT(*) FROM chunks WHERE document_id = :filing_id
            """), {"filing_id": filing_id}).scalar()

            chunks = session.execute(text("""
                SELECT id, section, chunk_index, text, token_count
                FROM chunks
                WHERE document_id = :filing_id
                ORDER BY chunk_index ASC
                LIMIT :limit OFFSET :offset
            """), {"filing_id": filing_id, "limit": page_size, "offset": offset})

            chunk_list = [
                {
                    "id": c.id,
                    "section": c.section,
                    "chunk_index": c.chunk_index,
                    "text": c.text,
                    "token_count": c.token_count,
                }
                for c in chunks
            ]

            return {
                **filing_meta,
                "chunks": chunk_list,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_chunks": total,
                    "total_pages": (total + page_size - 1) // page_size if total else 0,
                },
            }


@router.get("/edgar/filings/{filing_id}/sections")
async def get_filing_sections(filing_id: int):
    """
    Get section outline of a filing.

    Returns unique section labels and chunk counts per section,
    useful for building a table of contents / navigation sidebar.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_edgar_source_session

    with get_edgar_source_session() as session:
        result = session.execute(text("""
            SELECT
                section,
                MIN(chunk_index) as start_index,
                MAX(chunk_index) as end_index,
                COUNT(*) as chunk_count,
                SUM(token_count) as total_tokens
            FROM chunks
            WHERE document_id = :filing_id
            GROUP BY section
            ORDER BY MIN(chunk_index)
        """), {"filing_id": filing_id})

        sections = [
            {
                "section": row.section,
                "start_index": row.start_index,
                "end_index": row.end_index,
                "chunk_count": row.chunk_count,
                "total_tokens": row.total_tokens,
            }
            for row in result
        ]

        if not sections:
            raise HTTPException(status_code=404, detail="Filing not found or has no chunks")

    return {"filing_id": filing_id, "sections": sections}


@router.get("/edgar/filings/{filing_id}/related-deals")
async def get_filing_related_deals(filing_id: int):
    """
    Find Cortellis deals potentially related to a SEC filing.

    Cross-references by:
    1. Company match (via company_xref CIK linking)
    2. Date proximity (deals within 30 days of filing)
    3. Edgar extracted deals linked to this document
    """
    from sqlalchemy import text
    from unified_api.services.database import get_edgar_source_session, get_cortellis_session

    # Get filing info
    with get_edgar_source_session() as edgar_session:
        doc = edgar_session.execute(text("""
            SELECT d.id, d.published_at,
                   COALESCE(d.subtype, d.doc_type) AS doc_type, d.accession_no,
                   e.cik, e.name as company_name, r.filing_date
            FROM documents d
            JOIN raw_documents r ON d.raw_document_id = r.id
            JOIN companies e ON r.company_id = e.id
            WHERE d.id = :filing_id
        """), {"filing_id": filing_id}).fetchone()

        if not doc:
            raise HTTPException(status_code=404, detail="Filing not found")

        # Get Edgar extracted deals linked to this filing
        edgar_deals = edgar_session.execute(text("""
            SELECT DISTINCT d.id, d.deal_type, d.announced_at, d.description, d.status
            FROM provenance p
            JOIN deals d ON p.deal_id = d.id
            WHERE p.document_id = :filing_id
        """), {"filing_id": filing_id})

        extracted_deals = [
            {
                "source": "edgar_extracted",
                "id": row.id,
                "deal_type": row.deal_type,
                "announced_at": str(row.announced_at) if row.announced_at else None,
                "description": row.description[:300] + "..." if row.description and len(row.description) > 300 else row.description,
                "status": row.status,
            }
            for row in edgar_deals
        ]

    # Find Cortellis deals by company + date proximity
    cortellis_deals = []
    if doc.cik:
        filing_date = doc.filing_date or doc.published_at
        with get_cortellis_session() as ct_session:
            # Find the Cortellis company via CIK
            company = ct_session.execute(text("""
                SELECT id, name FROM companies WHERE cik = :cik
            """), {"cik": doc.cik}).fetchone()

            if company and filing_date:
                from datetime import timedelta
                date_from = filing_date - timedelta(days=30)
                date_to = filing_date + timedelta(days=30)
                deals = ct_session.execute(text("""
                    SELECT
                        d.id, d.title, d.agreement_type, d.status,
                        d.date_start::text,
                        f.total_projected_current_amount as total_value
                    FROM deal_companies dc
                    JOIN deals d ON d.id = dc.deal_id
                    LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
                    WHERE dc.company_id = :company_id
                      AND d.date_start BETWEEN :date_from AND :date_to
                    ORDER BY d.date_start DESC
                    LIMIT 10
                """), {
                    "company_id": company.id,
                    "date_from": date_from,
                    "date_to": date_to,
                })

                cortellis_deals = [
                    {
                        "source": "cortellis",
                        "id": row.id,
                        "title": row.title,
                        "agreement_type": row.agreement_type,
                        "status": row.status,
                        "date_start": row.date_start,
                        "total_value": float(row.total_value) if row.total_value else None,
                    }
                    for row in deals
                ]

    return {
        "filing": {
            "id": doc.id,
            "doc_type": doc.doc_type,
            "accession_no": doc.accession_no,
            "company_name": doc.company_name,
            "cik": doc.cik,
            "filing_date": str(doc.filing_date) if doc.filing_date else None,
        },
        "edgar_extracted_deals": extracted_deals,
        "cortellis_deals": cortellis_deals,
        "total_related": len(extracted_deals) + len(cortellis_deals),
    }


@router.get("/edgar/stats")
async def get_edgar_stats():
    """Get statistics about Edgar BD data."""
    from sqlalchemy import text
    from unified_api.services.database import get_edgar_session

    with get_edgar_session() as session:
        stats = {}

        # Company count
        stats["companies"] = session.execute(text(
            "SELECT COUNT(*) FROM companies"
        )).scalar()

        # Filing counts by type
        doc_types = session.execute(text("""
            SELECT doc_type, COUNT(*) as count
            FROM documents
            GROUP BY doc_type
            ORDER BY count DESC
            LIMIT 10
        """))
        stats["filings_by_type"] = {row.doc_type: row.count for row in doc_types}

        # Total documents
        stats["total_documents"] = session.execute(text(
            "SELECT COUNT(*) FROM documents"
        )).scalar()

        # Total chunks
        stats["total_chunks"] = session.execute(text(
            "SELECT COUNT(*) FROM chunks"
        )).scalar()

        # Deals extracted
        stats["deals_extracted"] = session.execute(text(
            "SELECT COUNT(*) FROM deals"
        )).scalar()

        return stats
