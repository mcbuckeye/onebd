"""FastAPI backend for Cortellis search chat interface."""

import logging
import os
import re
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Optional
from enum import Enum

from fastapi import FastAPI, HTTPException


def strip_xml_tags(text: str | None) -> str | None:
    """Remove XML/HTML tags from text content."""
    if not text:
        return text
    # Remove XML tags like <para>, <ulink ...>, </ulink>, <br/>, etc.
    cleaned = re.sub(r'<[^>]+>', ' ', text)
    # Collapse multiple spaces
    cleaned = re.sub(r'\s+', ' ', cleaned)
    return cleaned.strip()
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import load_config
from src.contract_indexer import ContractIndexer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global instances
config = None
query_agent = None
contract_indexer = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup."""
    global config, query_agent, contract_indexer

    logger.info("Initializing Cortellis API...")
    config = load_config()

    # Initialize contract indexer
    contract_indexer = ContractIndexer(config)

    # Initialize query agent
    from agent.query_agent import QueryAgent
    query_agent = QueryAgent(config)

    logger.info("API initialized successfully")
    yield

    logger.info("Shutting down API...")


app = FastAPI(
    title="Cortellis Search API",
    description="AI-powered search interface for Cortellis Deals Database",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchMode(str, Enum):
    AUTO = "auto"
    SQL = "sql"
    RAG = "rag"


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    mode: SearchMode = SearchMode.AUTO
    history: Optional[List[ChatMessage]] = None  # Previous messages for context


class SearchResult(BaseModel):
    deal_id: int
    deal_title: str
    contract_id: Optional[int] = None
    snippet: str
    relevance: float
    contract_types: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    mode_used: str
    sql_query: Optional[str] = None
    results_count: Optional[int] = None
    search_results: Optional[List[SearchResult]] = None
    timestamp: str


class IndexStatus(BaseModel):
    total_text_contracts: int
    indexed_for_fulltext: int
    total_chunks: int
    embedded_chunks: int
    fulltext_pct: float
    embedding_pct: float


class HealthResponse(BaseModel):
    status: str
    database: str
    openai: str
    timestamp: str


# Deal detail response models
class CompanyInfo(BaseModel):
    id: int
    name: str
    role: str
    company_type: Optional[str] = None
    hq_location: Optional[str] = None


class FinanceSummary(BaseModel):
    total_paid_amount: Optional[float] = None
    total_paid_disclosure_status: Optional[str] = None
    total_projected_current_amount: Optional[float] = None
    total_projected_signing_amount: Optional[float] = None


class TimelineEvent(BaseModel):
    event_date: Optional[str] = None
    event_type: Optional[str] = None
    stage: Optional[str] = None
    summary: Optional[str] = None


class ContractInfo(BaseModel):
    id: int
    contract_types: Optional[str] = None
    date_filing: Optional[str] = None
    date_contract: Optional[str] = None
    has_pdf: bool
    has_text: bool


# Entity info models (for clickable links)
class EntityInfo(BaseModel):
    id: int
    name: str


class DrugInfo(BaseModel):
    id: int
    name: str
    phase_highest_now: Optional[str] = None


class DealDetail(BaseModel):
    id: int
    title: str
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
    contracts: List[ContractInfo] = []


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Check API health and dependencies."""
    db_status = "unknown"
    openai_status = "unknown"

    try:
        # Check database
        from sqlalchemy import text
        with contract_indexer.SessionLocal() as session:
            session.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        db_status = f"error: {str(e)}"

    # Check OpenAI
    if config.openai.api_key:
        openai_status = "configured"
    else:
        openai_status = "not configured"

    return HealthResponse(
        status="healthy" if db_status == "healthy" else "degraded",
        database=db_status,
        openai=openai_status,
        timestamp=datetime.utcnow().isoformat(),
    )


@app.get("/index-status", response_model=IndexStatus)
async def get_index_status():
    """Get contract indexing status."""
    stats = contract_indexer.get_stats()

    fulltext_pct = 0.0
    if stats['total_text_contracts'] > 0:
        fulltext_pct = (stats['indexed_for_fulltext'] / stats['total_text_contracts']) * 100

    embedding_pct = 0.0
    if stats['total_chunks'] > 0:
        embedding_pct = (stats['embedded_chunks'] / stats['total_chunks']) * 100

    return IndexStatus(
        total_text_contracts=stats['total_text_contracts'],
        indexed_for_fulltext=stats['indexed_for_fulltext'],
        total_chunks=stats['total_chunks'],
        embedded_chunks=stats['embedded_chunks'],
        fulltext_pct=round(fulltext_pct, 1),
        embedding_pct=round(embedding_pct, 1),
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Process a chat message and return response."""
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    try:
        message = request.message.strip()
        mode_used = "sql"
        sql_query = None
        search_results = None
        results_count = None

        # Determine mode
        use_rag = False
        if request.mode == SearchMode.RAG:
            use_rag = True
        elif request.mode == SearchMode.AUTO:
            use_rag = query_agent.needs_contract_search(message)

        if use_rag:
            # RAG mode - search contracts
            mode_used = "rag"
            context = query_agent.get_relevant_contract_context(message, limit=5)

            if context:
                response = query_agent._answer_with_rag(message, context)

                # Get search results for display
                raw_results = contract_indexer.search_similar(message, limit=5)
                search_results = [
                    SearchResult(
                        deal_id=r['deal_id'],
                        deal_title=r['deal_title'][:100],
                        contract_id=r['contract_id'],
                        snippet=r['content'][:300] + "..." if len(r['content']) > 300 else r['content'],
                        relevance=round(r['similarity'], 4),
                        contract_types=r.get('contract_types'),
                    )
                    for r in raw_results
                ]
                results_count = len(search_results)
            else:
                response = "No relevant contract content found for your query. Try rephrasing or use SQL mode for structured data queries."
        else:
            # SQL mode
            mode_used = "sql"
            # Convert history to format expected by query agent
            history = None
            if request.history:
                history = [{"role": m.role, "content": m.content} for m in request.history]
            sql_query = query_agent.generate_sql(message, history=history)
            result = query_agent.execute_sql(sql_query)

            if result.error:
                response = f"SQL Error: {result.error}"
            else:
                results_count = len(result.rows)

                # Format results as markdown table
                if result.rows:
                    explanation = query_agent.explain_results(message, result)

                    # Build table
                    table_md = "| " + " | ".join(result.columns) + " |\n"
                    table_md += "| " + " | ".join(["---"] * len(result.columns)) + " |\n"

                    for row in result.rows[:50]:  # Limit to 50 rows
                        table_md += "| " + " | ".join(str(v) if v is not None else "" for v in row) + " |\n"

                    if len(result.rows) > 50:
                        table_md += f"\n*...and {len(result.rows) - 50} more rows*\n"

                    response = f"{explanation}\n\n**Results ({results_count} rows):**\n\n{table_md}"
                else:
                    response = "No results found for your query."

        return ChatResponse(
            response=response,
            mode_used=mode_used,
            sql_query=sql_query,
            results_count=results_count,
            search_results=search_results,
            timestamp=datetime.utcnow().isoformat(),
        )

    except Exception as e:
        logger.exception("Error processing chat request")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/search/fulltext")
async def search_fulltext(query: str, limit: int = 10):
    """Full-text search in contracts."""
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    results = contract_indexer.search_fulltext(query, limit=limit)
    return {"results": results, "count": len(results)}


@app.get("/search/similar")
async def search_similar(query: str, limit: int = 5):
    """Semantic similarity search in contracts."""
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    if not config.openai.api_key:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured")

    results = contract_indexer.search_similar(query, limit=limit)
    return {"results": results, "count": len(results)}


@app.get("/deal/{deal_id}", response_model=DealDetail)
async def get_deal_detail(deal_id: int):
    """Get comprehensive deal details by ID."""
    from sqlalchemy import text

    try:
        with contract_indexer.SessionLocal() as session:
            # Get main deal info
            deal_query = text("""
                SELECT d.id, d.title, d.deal_type, d.status, d.date_start, d.date_end,
                       d.summary, d.agreement_type, d.asset_type, d.transaction_type,
                       d.phase_highest_start, d.phase_highest_now, d.is_merger_acquisition,
                       ta.name as therapy_area
                FROM deals d
                LEFT JOIN therapy_areas ta ON d.therapy_area_id = ta.id
                WHERE d.id = :deal_id
            """)
            deal_row = session.execute(deal_query, {"deal_id": deal_id}).fetchone()

            if not deal_row:
                raise HTTPException(status_code=404, detail=f"Deal {deal_id} not found")

            # Get companies
            companies_query = text("""
                SELECT c.id, c.name, dc.role, c.company_type, c.hq_location
                FROM deal_companies dc
                JOIN companies c ON dc.company_id = c.id
                WHERE dc.deal_id = :deal_id
                ORDER BY dc.role
            """)
            companies = [
                CompanyInfo(
                    id=row.id, name=row.name, role=row.role,
                    company_type=row.company_type, hq_location=row.hq_location
                )
                for row in session.execute(companies_query, {"deal_id": deal_id})
            ]

            # Get indications
            indications_query = text("""
                SELECT i.id, i.name FROM deal_indications di
                JOIN indications i ON di.indication_id = i.id
                WHERE di.deal_id = :deal_id
            """)
            indications = [
                EntityInfo(id=row.id, name=row.name)
                for row in session.execute(indications_query, {"deal_id": deal_id})
            ]

            # Get technologies
            tech_query = text("""
                SELECT t.id, t.name FROM deal_technologies dt
                JOIN technologies t ON dt.technology_id = t.id
                WHERE dt.deal_id = :deal_id
            """)
            technologies = [
                EntityInfo(id=row.id, name=row.name)
                for row in session.execute(tech_query, {"deal_id": deal_id})
            ]

            # Get drugs
            drugs_query = text("""
                SELECT dr.id, dr.name_display, dr.phase_highest_now
                FROM deal_drugs dd
                JOIN drugs dr ON dd.drug_id = dr.id
                WHERE dd.deal_id = :deal_id
            """)
            drugs = [
                DrugInfo(id=row.id, name=row.name_display, phase_highest_now=row.phase_highest_now)
                for row in session.execute(drugs_query, {"deal_id": deal_id})
            ]

            # Get territories
            territories_query = text("""
                SELECT t.name, dt.territory_type FROM deal_territories dt
                JOIN territories t ON dt.territory_id = t.id
                WHERE dt.deal_id = :deal_id
            """)
            territories_included = []
            territories_excluded = []
            for row in session.execute(territories_query, {"deal_id": deal_id}):
                if row.territory_type == "Included":
                    territories_included.append(row.name)
                else:
                    territories_excluded.append(row.name)

            # Get finance summary
            finance_query = text("""
                SELECT total_paid_amount, total_paid_disclosure_status,
                       total_projected_current_amount, total_projected_signing_amount
                FROM deal_finance_summary
                WHERE deal_id = :deal_id
            """)
            finance_row = session.execute(finance_query, {"deal_id": deal_id}).fetchone()
            finance = None
            if finance_row:
                finance = FinanceSummary(
                    total_paid_amount=finance_row.total_paid_amount,
                    total_paid_disclosure_status=finance_row.total_paid_disclosure_status,
                    total_projected_current_amount=finance_row.total_projected_current_amount,
                    total_projected_signing_amount=finance_row.total_projected_signing_amount,
                )

            # Get timeline events (most recent 10)
            timeline_query = text("""
                SELECT event_date, event_type, stage, summary
                FROM deal_timeline_events
                WHERE deal_id = :deal_id
                ORDER BY event_date DESC NULLS LAST
                LIMIT 10
            """)
            timeline = [
                TimelineEvent(
                    event_date=row.event_date.isoformat() if row.event_date else None,
                    event_type=row.event_type,
                    stage=row.stage,
                    summary=strip_xml_tags(row.summary[:500]) if row.summary else None,
                )
                for row in session.execute(timeline_query, {"deal_id": deal_id})
            ]

            # Get contracts
            contracts_query = text("""
                SELECT id, contract_types, date_filing, date_contract, has_pdf, has_text
                FROM deal_contracts
                WHERE deal_id = :deal_id
                ORDER BY date_filing DESC NULLS LAST
            """)
            contracts = [
                ContractInfo(
                    id=row.id,
                    contract_types=row.contract_types,
                    date_filing=row.date_filing.isoformat() if row.date_filing else None,
                    date_contract=row.date_contract.isoformat() if row.date_contract else None,
                    has_pdf=row.has_pdf,
                    has_text=row.has_text,
                )
                for row in session.execute(contracts_query, {"deal_id": deal_id})
            ]

            return DealDetail(
                id=deal_row.id,
                title=deal_row.title,
                deal_type=deal_row.deal_type,
                status=deal_row.status,
                therapy_area=deal_row.therapy_area,
                date_start=deal_row.date_start.isoformat() if deal_row.date_start else None,
                date_end=deal_row.date_end.isoformat() if deal_row.date_end else None,
                summary=strip_xml_tags(deal_row.summary),
                agreement_type=deal_row.agreement_type,
                asset_type=deal_row.asset_type,
                transaction_type=deal_row.transaction_type,
                phase_highest_start=deal_row.phase_highest_start,
                phase_highest_now=deal_row.phase_highest_now,
                is_merger_acquisition=deal_row.is_merger_acquisition,
                companies=companies,
                indications=indications,
                technologies=technologies,
                drugs=drugs,
                territories_included=territories_included,
                territories_excluded=territories_excluded,
                finance=finance,
                timeline=timeline,
                contracts=contracts,
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching deal {deal_id}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/contract/{contract_id}/pdf")
async def get_contract_pdf(contract_id: int):
    """Download contract PDF file."""
    from fastapi.responses import FileResponse
    from sqlalchemy import text
    import os

    try:
        with contract_indexer.SessionLocal() as session:
            query = text("""
                SELECT pdf_file_path, deal_id
                FROM deal_contracts
                WHERE id = :contract_id AND has_pdf = true
            """)
            row = session.execute(query, {"contract_id": contract_id}).fetchone()

            if not row or not row.pdf_file_path:
                raise HTTPException(status_code=404, detail="PDF not found")

            file_path = row.pdf_file_path
            if not os.path.isabs(file_path):
                file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), file_path)

            if not os.path.exists(file_path):
                raise HTTPException(status_code=404, detail="PDF file not found on disk")

            return FileResponse(
                file_path,
                media_type="application/pdf",
                filename=f"contract_{contract_id}.pdf"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching contract PDF {contract_id}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/contract/{contract_id}/text")
async def get_contract_text(contract_id: int):
    """Get contract text content."""
    from fastapi.responses import PlainTextResponse
    from sqlalchemy import text

    try:
        with contract_indexer.SessionLocal() as session:
            # First try to get from contract_content table (indexed content)
            query = text("""
                SELECT cc.content, dc.deal_id
                FROM contract_content cc
                JOIN deal_contracts dc ON cc.contract_id = dc.id
                WHERE dc.id = :contract_id
            """)
            row = session.execute(query, {"contract_id": contract_id}).fetchone()

            if row and row.content:
                return PlainTextResponse(row.content)

            # Fall back to text file if exists
            file_query = text("""
                SELECT text_file_path, deal_id
                FROM deal_contracts
                WHERE id = :contract_id AND has_text = true
            """)
            file_row = session.execute(file_query, {"contract_id": contract_id}).fetchone()

            if file_row and file_row.text_file_path:
                import os
                file_path = file_row.text_file_path
                if not os.path.isabs(file_path):
                    file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), file_path)

                if os.path.exists(file_path):
                    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                        return PlainTextResponse(f.read())

            raise HTTPException(status_code=404, detail="Contract text not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching contract text {contract_id}")
        raise HTTPException(status_code=500, detail=str(e))


# Entity detail response models
class DealSummary(BaseModel):
    id: int
    title: str
    status: Optional[str] = None
    date_start: Optional[str] = None
    total_value: Optional[float] = None


class EntityDetail(BaseModel):
    id: int
    name: str
    entity_type: str
    deal_count: int
    deals: List[DealSummary] = []


class DrugDetail(BaseModel):
    id: int
    name: str
    phase_highest_start: Optional[str] = None
    phase_highest_now: Optional[str] = None
    deal_count: int
    deals: List[DealSummary] = []


class CompanyDetail(BaseModel):
    id: int
    name: str
    company_type: Optional[str] = None
    hq_location: Optional[str] = None
    deal_count: int
    deals_as_principal: List[DealSummary] = []
    deals_as_partner: List[DealSummary] = []


@app.get("/entity/indication/{indication_id}", response_model=EntityDetail)
async def get_indication_detail(indication_id: int, limit: int = 20):
    """Get indication details and related deals."""
    from sqlalchemy import text as sql_text

    try:
        with contract_indexer.SessionLocal() as session:
            # Get indication info
            info_query = sql_text("SELECT id, name FROM indications WHERE id = :id")
            info = session.execute(info_query, {"id": indication_id}).fetchone()
            if not info:
                raise HTTPException(status_code=404, detail="Indication not found")

            # Get deal count
            count_query = sql_text("""
                SELECT COUNT(DISTINCT deal_id) as cnt FROM deal_indications WHERE indication_id = :id
            """)
            count = session.execute(count_query, {"id": indication_id}).fetchone().cnt

            # Get related deals
            deals_query = sql_text("""
                SELECT d.id, d.title, d.status, d.date_start, dfs.total_projected_current_amount
                FROM deals d
                JOIN deal_indications di ON d.id = di.deal_id
                LEFT JOIN deal_finance_summary dfs ON d.id = dfs.deal_id
                WHERE di.indication_id = :id
                ORDER BY d.date_start DESC NULLS LAST
                LIMIT :limit
            """)
            deals = [
                DealSummary(
                    id=row.id, title=row.title, status=row.status,
                    date_start=row.date_start.isoformat() if row.date_start else None,
                    total_value=row.total_projected_current_amount
                )
                for row in session.execute(deals_query, {"id": indication_id, "limit": limit})
            ]

            return EntityDetail(
                id=info.id, name=info.name, entity_type="indication",
                deal_count=count, deals=deals
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching indication {indication_id}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/entity/technology/{technology_id}", response_model=EntityDetail)
async def get_technology_detail(technology_id: int, limit: int = 20):
    """Get technology details and related deals."""
    from sqlalchemy import text as sql_text

    try:
        with contract_indexer.SessionLocal() as session:
            # Get technology info
            info_query = sql_text("SELECT id, name FROM technologies WHERE id = :id")
            info = session.execute(info_query, {"id": technology_id}).fetchone()
            if not info:
                raise HTTPException(status_code=404, detail="Technology not found")

            # Get deal count
            count_query = sql_text("""
                SELECT COUNT(DISTINCT deal_id) as cnt FROM deal_technologies WHERE technology_id = :id
            """)
            count = session.execute(count_query, {"id": technology_id}).fetchone().cnt

            # Get related deals
            deals_query = sql_text("""
                SELECT d.id, d.title, d.status, d.date_start, dfs.total_projected_current_amount
                FROM deals d
                JOIN deal_technologies dt ON d.id = dt.deal_id
                LEFT JOIN deal_finance_summary dfs ON d.id = dfs.deal_id
                WHERE dt.technology_id = :id
                ORDER BY d.date_start DESC NULLS LAST
                LIMIT :limit
            """)
            deals = [
                DealSummary(
                    id=row.id, title=row.title, status=row.status,
                    date_start=row.date_start.isoformat() if row.date_start else None,
                    total_value=row.total_projected_current_amount
                )
                for row in session.execute(deals_query, {"id": technology_id, "limit": limit})
            ]

            return EntityDetail(
                id=info.id, name=info.name, entity_type="technology",
                deal_count=count, deals=deals
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching technology {technology_id}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/entity/drug/{drug_id}", response_model=DrugDetail)
async def get_drug_detail(drug_id: int, limit: int = 20):
    """Get drug details and related deals."""
    from sqlalchemy import text as sql_text

    try:
        with contract_indexer.SessionLocal() as session:
            # Get drug info
            info_query = sql_text("""
                SELECT id, name_display, phase_highest_start, phase_highest_now
                FROM drugs WHERE id = :id
            """)
            info = session.execute(info_query, {"id": drug_id}).fetchone()
            if not info:
                raise HTTPException(status_code=404, detail="Drug not found")

            # Get deal count
            count_query = sql_text("""
                SELECT COUNT(DISTINCT deal_id) as cnt FROM deal_drugs WHERE drug_id = :id
            """)
            count = session.execute(count_query, {"id": drug_id}).fetchone().cnt

            # Get related deals
            deals_query = sql_text("""
                SELECT d.id, d.title, d.status, d.date_start, dfs.total_projected_current_amount
                FROM deals d
                JOIN deal_drugs dd ON d.id = dd.deal_id
                LEFT JOIN deal_finance_summary dfs ON d.id = dfs.deal_id
                WHERE dd.drug_id = :id
                ORDER BY d.date_start DESC NULLS LAST
                LIMIT :limit
            """)
            deals = [
                DealSummary(
                    id=row.id, title=row.title, status=row.status,
                    date_start=row.date_start.isoformat() if row.date_start else None,
                    total_value=row.total_projected_current_amount
                )
                for row in session.execute(deals_query, {"id": drug_id, "limit": limit})
            ]

            return DrugDetail(
                id=info.id, name=info.name_display,
                phase_highest_start=info.phase_highest_start,
                phase_highest_now=info.phase_highest_now,
                deal_count=count, deals=deals
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching drug {drug_id}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/entity/company/{company_id}", response_model=CompanyDetail)
async def get_company_detail(company_id: int, limit: int = 20):
    """Get company details and related deals."""
    from sqlalchemy import text as sql_text

    try:
        with contract_indexer.SessionLocal() as session:
            # Get company info
            info_query = sql_text("""
                SELECT id, name, company_type, hq_location FROM companies WHERE id = :id
            """)
            info = session.execute(info_query, {"id": company_id}).fetchone()
            if not info:
                raise HTTPException(status_code=404, detail="Company not found")

            # Get deal count
            count_query = sql_text("""
                SELECT COUNT(DISTINCT deal_id) as cnt FROM deal_companies WHERE company_id = :id
            """)
            count = session.execute(count_query, {"id": company_id}).fetchone().cnt

            # Get deals as principal
            principal_query = sql_text("""
                SELECT d.id, d.title, d.status, d.date_start, dfs.total_projected_current_amount
                FROM deals d
                JOIN deal_companies dc ON d.id = dc.deal_id
                LEFT JOIN deal_finance_summary dfs ON d.id = dfs.deal_id
                WHERE dc.company_id = :id AND dc.role = 'Principal'
                ORDER BY d.date_start DESC NULLS LAST
                LIMIT :limit
            """)
            deals_principal = [
                DealSummary(
                    id=row.id, title=row.title, status=row.status,
                    date_start=row.date_start.isoformat() if row.date_start else None,
                    total_value=row.total_projected_current_amount
                )
                for row in session.execute(principal_query, {"id": company_id, "limit": limit})
            ]

            # Get deals as partner
            partner_query = sql_text("""
                SELECT d.id, d.title, d.status, d.date_start, dfs.total_projected_current_amount
                FROM deals d
                JOIN deal_companies dc ON d.id = dc.deal_id
                LEFT JOIN deal_finance_summary dfs ON d.id = dfs.deal_id
                WHERE dc.company_id = :id AND dc.role = 'Partner'
                ORDER BY d.date_start DESC NULLS LAST
                LIMIT :limit
            """)
            deals_partner = [
                DealSummary(
                    id=row.id, title=row.title, status=row.status,
                    date_start=row.date_start.isoformat() if row.date_start else None,
                    total_value=row.total_projected_current_amount
                )
                for row in session.execute(partner_query, {"id": company_id, "limit": limit})
            ]

            return CompanyDetail(
                id=info.id, name=info.name,
                company_type=info.company_type, hq_location=info.hq_location,
                deal_count=count,
                deals_as_principal=deals_principal,
                deals_as_partner=deals_partner
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error fetching company {company_id}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
