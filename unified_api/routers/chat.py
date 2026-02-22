"""
Chat endpoints for natural language queries.
Routes queries to appropriate backend (SQL, RAG, or Graph).
"""
from typing import Optional, List, Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()


class ChatMessage(BaseModel):
    """A message in chat history."""
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    """Request for chat endpoint."""
    message: str
    mode: Literal["auto", "sql", "rag", "graph"] = "auto"
    history: Optional[List[ChatMessage]] = None


class SearchResult(BaseModel):
    """A search result from RAG - matches frontend expectations."""
    deal_id: int
    deal_title: str
    contract_id: Optional[int] = None
    snippet: str
    relevance: float
    contract_types: Optional[str] = None


class ChatResponse(BaseModel):
    """Response from chat endpoint."""
    response: str
    mode_used: str
    sql_query: Optional[str] = None
    search_results: Optional[List[SearchResult]] = None
    data: Optional[List[dict]] = None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Process a natural language query.

    Modes:
    - **auto**: LLM decides whether to use SQL, RAG, or Graph queries
    - **sql**: Force SQL query against Cortellis deals database
    - **rag**: Force semantic search against contract/filing embeddings
    - **graph**: Force Cypher query against Neo4j relationship graph

    The query router uses the LLM to:
    1. Classify the query intent
    2. Generate appropriate query (SQL/Cypher/embedding search)
    3. Execute against the appropriate backend
    4. Format and return results
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session
    from unified_api.services.llm import get_llm_service
    from unified_api.services.embed import get_embedding_provider

    logger.info(
        "Processing chat request",
        mode=request.mode,
        message_length=len(request.message),
    )

    llm_service = get_llm_service()

    # Determine mode
    if request.mode == "auto":
        intent = await llm_service.classify_intent(request.message)
        logger.info("Auto-classified intent", intent=intent)

        # Map intent to mode
        if intent in ["deal_search", "company_lookup", "drug_lookup", "valuation", "market_trends"]:
            mode = "sql"
        elif intent in ["contract_search"]:
            mode = "rag"
        elif intent in ["relationship", "company_compare"]:
            mode = "graph"
        else:
            mode = "sql"  # Default to SQL for general queries
    else:
        mode = request.mode
        intent = None

    try:
        if mode == "sql":
            return await _handle_sql_query(request.message, llm_service)
        elif mode == "rag":
            return await _handle_rag_query(request.message)
        elif mode == "graph":
            return await _handle_graph_query(request.message, llm_service)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}")

    except Exception as e:
        logger.error("Chat processing failed", error=str(e), mode=mode)
        return ChatResponse(
            response=f"Sorry, I encountered an error processing your request: {str(e)}",
            mode_used=mode,
        )


async def _handle_sql_query(message: str, llm_service) -> ChatResponse:
    """Handle SQL-based queries."""
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    # Generate SQL
    sql_query = await llm_service.generate_sql(message)

    # Validate and clean SQL (basic safety check)
    sql_lower = sql_query.lower()
    if any(keyword in sql_lower for keyword in ['drop', 'delete', 'update', 'insert', 'alter', 'truncate']):
        return ChatResponse(
            response="I can only run SELECT queries for safety reasons.",
            mode_used="sql",
            sql_query=sql_query,
        )

    # Execute query
    try:
        with get_cortellis_session() as session:
            result = session.execute(text(sql_query))
            rows = result.fetchall()

            # Convert to list of dicts
            if rows:
                columns = result.keys()
                data = [dict(zip(columns, row)) for row in rows]
            else:
                data = []

        # Format response
        response_text = await llm_service.format_response(message, data)

        return ChatResponse(
            response=response_text,
            mode_used="sql",
            sql_query=sql_query,
            data=data[:20],  # Limit data in response
        )

    except Exception as e:
        logger.error("SQL execution failed", error=str(e), sql=sql_query[:200])
        return ChatResponse(
            response=f"I generated a query but it failed to execute. Error: {str(e)[:200]}",
            mode_used="sql",
            sql_query=sql_query,
        )


async def _handle_rag_query(message: str) -> ChatResponse:
    """Handle RAG-based contract search queries."""
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session
    from unified_api.services.embed import get_embedding_provider
    from unified_api.services.llm import get_llm_service

    llm_service = get_llm_service()

    # Generate embedding for query
    embedding_provider = get_embedding_provider()
    query_embedding = await embedding_provider.embed_single(message)
    embedding_str = "[" + ",".join(str(x) for x in query_embedding) + "]"

    # Search contract chunks
    with get_cortellis_session() as session:
        result = session.execute(text("""
            SELECT
                cc.id,
                cc.deal_id,
                cc.contract_id,
                cc.content,
                1 - (cc.embedding <=> CAST(:embedding AS vector)) as similarity,
                d.title as deal_title,
                dc_contract.contract_types,
                (SELECT c.name FROM deal_companies dcomp
                 JOIN companies c ON c.id = dcomp.company_id
                 WHERE dcomp.deal_id = cc.deal_id AND dcomp.role = 'Principal' LIMIT 1) as principal
            FROM contract_chunks cc
            JOIN deals d ON d.id = cc.deal_id
            LEFT JOIN deal_contracts dc_contract ON dc_contract.id = cc.contract_id
            WHERE cc.embedding IS NOT NULL
            ORDER BY cc.embedding <=> CAST(:embedding AS vector)
            LIMIT 10
        """), {"embedding": embedding_str})

        chunks = []
        search_results = []
        for row in result:
            chunks.append({
                "deal_id": row.deal_id,
                "deal_title": row.deal_title,
                "principal": row.principal,
                "content": row.content[:500],
                "similarity": float(row.similarity),
            })
            snippet = row.content[:300] + "..." if len(row.content) > 300 else row.content
            search_results.append(SearchResult(
                deal_id=row.deal_id,
                deal_title=row.deal_title or "Unknown Deal",
                contract_id=row.contract_id,
                snippet=snippet,
                relevance=float(row.similarity),
                contract_types=row.contract_types,
            ))

    # Format response using LLM
    if chunks:
        response_text = await llm_service.format_response(message, chunks)
    else:
        response_text = "I couldn't find any relevant contract content for your query."

    return ChatResponse(
        response=response_text,
        mode_used="rag",
        search_results=search_results,
    )


async def _handle_graph_query(message: str, llm_service) -> ChatResponse:
    """Handle graph-based relationship queries."""
    from unified_api.services.graph_sync import get_graph_sync_service

    # For now, handle common graph query patterns
    message_lower = message.lower()

    graph_service = get_graph_sync_service()
    driver = graph_service._get_driver()

    data = []

    try:
        with driver.session() as session:
            # Pattern: "Who partners with X" or "X's partners"
            if "partner" in message_lower:
                # Extract company name (simple heuristic)
                # A real implementation would use NER
                company_keywords = message_lower.replace("who partners with", "").replace("'s partners", "").replace("partners of", "").strip()

                result = session.run("""
                    MATCH (c:Company)-[]->(d:Deal)<-[]-(partner:Company)
                    WHERE toLower(c.name) CONTAINS $keyword AND c.id <> partner.id
                    WITH partner, count(DISTINCT d) as deal_count
                    ORDER BY deal_count DESC
                    LIMIT 10
                    RETURN partner.name as name, partner.company_type as type, deal_count
                """, {"keyword": company_keywords[:20]})

                for row in result:
                    data.append({
                        "partner": row["name"],
                        "type": row["type"],
                        "deal_count": row["deal_count"],
                    })

            # Pattern: "path between X and Y"
            elif "path" in message_lower or "connect" in message_lower:
                # Extract company names
                result = session.run("""
                    MATCH (c:Company)
                    WHERE c.source = 'cortellis'
                    RETURN c.name as name, c.id as id
                    ORDER BY size((c)-[]->()) DESC
                    LIMIT 100
                """)
                data = [{"name": row["name"], "id": row["id"]} for row in result]

            # Pattern: "most active" or "top companies"
            elif "most active" in message_lower or "top" in message_lower:
                result = session.run("""
                    MATCH (c:Company)-[r]->(d:Deal)
                    WITH c, count(d) as deal_count
                    ORDER BY deal_count DESC
                    LIMIT 20
                    RETURN c.name as name, c.company_type as type, deal_count
                """)
                data = [{"name": row["name"], "type": row["type"], "deals": row["deal_count"]} for row in result]

            else:
                # Default: show top partnering companies
                result = session.run("""
                    MATCH (c:Company)-[]->(d:Deal)
                    WITH c, count(DISTINCT d) as deal_count
                    ORDER BY deal_count DESC
                    LIMIT 10
                    RETURN c.name as name, deal_count
                """)
                data = [{"company": row["name"], "deals": row["deal_count"]} for row in result]

        # Format response
        response_text = await llm_service.format_response(message, data)

        return ChatResponse(
            response=response_text,
            mode_used="graph",
            data=data,
        )

    except Exception as e:
        logger.error("Graph query failed", error=str(e))
        return ChatResponse(
            response=f"I had trouble querying the relationship graph: {str(e)[:200]}",
            mode_used="graph",
        )


@router.post("/chat/sql")
async def chat_sql(request: ChatRequest):
    """
    Generate and execute SQL from natural language.
    Returns both the generated SQL and results.
    """
    from unified_api.services.llm import get_llm_service
    llm_service = get_llm_service()
    return await _handle_sql_query(request.message, llm_service)


@router.post("/chat/rag")
async def chat_rag(request: ChatRequest):
    """
    Search contracts using semantic similarity.
    Returns relevant contract excerpts.
    """
    return await _handle_rag_query(request.message)


class ChatV2Response(BaseModel):
    """Enhanced chat response with synthesis."""
    answer: str
    intent: str
    confidence: dict
    data: Optional[List[dict]] = None
    sql_query: Optional[str] = None
    follow_ups: List[str] = []
    actions: List[dict] = []


@router.post("/chat/v2", response_model=ChatV2Response)
async def chat_v2(request: ChatRequest):
    """
    Enhanced conversational intelligence endpoint.

    Returns synthesized answers with:
    - Narrative response (not raw data)
    - Confidence indicators (sample size, disclosure rate)
    - Follow-up suggestions
    - Action links (save search, export, view dashboard)
    """
    from unified_api.services.llm import get_llm_service

    llm_service = get_llm_service()

    # Classify intent
    intent = await llm_service.classify_intent(request.message)

    # Route to appropriate handler and get raw data
    if intent in ["contract_search"]:
        raw_response = await _handle_rag_query(request.message)
        mode = "rag"
        data = [r.model_dump() for r in (raw_response.search_results or [])]
        sql_query = None
    elif intent in ["relationship", "company_compare"]:
        raw_response = await _handle_graph_query(request.message, llm_service)
        mode = "graph"
        data = raw_response.data or []
        sql_query = None
    else:
        raw_response = await _handle_sql_query(request.message, llm_service)
        mode = "sql"
        data = raw_response.data or []
        sql_query = raw_response.sql_query

    # Synthesize response
    synthesis = await llm_service.synthesize_response(request.message, mode, data)

    # Build action suggestions
    actions = [
        {"label": "Export to Excel", "type": "export", "params": {"format": "excel"}},
    ]
    if data:
        actions.append({"label": "Save Search", "type": "save_search", "params": {"query": request.message}})
    if intent == "deal_search":
        actions.append({"label": "View in Search", "type": "navigate", "params": {"path": "/search"}})
    if intent == "market_trends":
        actions.append({"label": "View Analytics", "type": "navigate", "params": {"path": "/analytics"}})

    return ChatV2Response(
        answer=synthesis["answer"],
        intent=intent,
        confidence=synthesis["confidence"],
        data=data[:10],
        sql_query=sql_query,
        follow_ups=synthesis["follow_ups"],
        actions=actions,
    )
