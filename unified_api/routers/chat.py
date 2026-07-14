"""
Chat endpoints for natural language queries.
Routes queries to appropriate backend (SQL, RAG, or Graph).
"""
import re
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
    resolved_entities: List[dict] = []
    citations: List[dict] = []


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
    from unified_api.services.llm import get_llm_service

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
        elif intent in ["relationship", "company_compare"] and not _is_deal_pattern_query(
            request.message
        ):
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

    from unified_api.services.question_context import (
        resolve_company_mentions,
        resolve_drug_mentions,
    )
    from unified_api.services.governed_metrics import build_citations

    metric_limitation = _structured_metric_limitation(message)
    if metric_limitation:
        return ChatResponse(
            response=metric_limitation,
            mode_used="sql",
            data=[],
        )

    resolved_entities = resolve_company_mentions(message)
    resolved_entities.extend(resolve_drug_mentions(message))
    ambiguous = [
        entity for entity in resolved_entities if entity.get("status") == "ambiguous"
    ]
    if ambiguous:
        choices = "; ".join(
            f"{entity['mention']}: " + ", ".join(
                f"{candidate['canonical_name']} (ID "
                f"{candidate.get('company_id') or candidate.get('drug_id')})"
                for candidate in entity.get("candidates", [])
            )
            for entity in ambiguous
        )
        return ChatResponse(
            response=f"The entity name is ambiguous. Please choose one of: {choices}",
            mode_used="sql",
            data=[],
            resolved_entities=resolved_entities,
        )

    # Use governed templates for common metrics; fall back to LLM generation for
    # questions that do not yet have a deterministic query shape.
    sql_query = _build_governed_sql(message, resolved_entities)
    if sql_query is None:
        sql_query = await llm_service.generate_sql(
            message,
            resolved_entities=resolved_entities,
        )

    missing_ids = _missing_resolved_entity_ids(sql_query, resolved_entities)
    if missing_ids:
        return ChatResponse(
            response=(
                "The generated query did not preserve the resolved entity identity, "
                "so it was not executed. Please retry or select the entity explicitly."
            ),
            mode_used="sql",
            sql_query=sql_query,
            data=[],
            resolved_entities=resolved_entities,
        )

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
        if "clinical_trial" in sql_lower:
            from unified_api.services.clinical_trials import (
                ensure_clinical_trials_schema,
            )

            ensure_clinical_trials_schema()
        if "public_" in sql_lower or "drug_identifiers" in sql_lower:
            from unified_api.services.public_drug_enrichment import (
                ensure_public_drug_schema,
            )

            ensure_public_drug_schema()
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
        response_text = (
            await llm_service.format_response(message, data)
            if data
            else "No supporting database records were found for this question."
        )
        citations = build_citations("sql", data, sql_query)

        return ChatResponse(
            response=response_text,
            mode_used="sql",
            sql_query=sql_query,
            data=data[:20],  # Limit data in response
            resolved_entities=resolved_entities,
            citations=citations,
        )

    except Exception as e:
        logger.error("SQL execution failed", error=str(e), sql=sql_query[:200])
        return ChatResponse(
            response=f"I generated a query but it failed to execute. Error: {str(e)[:200]}",
            mode_used="sql",
            sql_query=sql_query,
            resolved_entities=resolved_entities,
        )


def _structured_metric_limitation(message: str) -> Optional[str]:
    """Refuse aggregate metrics that do not yet have a governed structured field."""
    from unified_api.services.governed_metrics import metric_limitation

    return metric_limitation(message)


def _missing_resolved_entity_ids(sql_query: str, resolved_entities: List[dict]) -> List[int]:
    """Require generated SQL to bind every unambiguous entity to its canonical ID."""
    missing = []
    for entity in resolved_entities:
        if entity.get("status") != "resolved":
            continue
        entity_id = entity.get("company_id") or entity.get("drug_id")
        if entity_id is None:
            continue
        entity_id = int(entity_id)
        if not re.search(rf"(?<!\d){entity_id}(?!\d)", sql_query):
            missing.append(entity_id)
    return missing


def _is_deal_pattern_query(message: str) -> bool:
    """Keep strategy-from-deals questions on governed relational data."""
    normalized = message.lower()
    return "strategy" in normalized and "deal pattern" in normalized


def _build_governed_sql(message: str, resolved_entities: List[dict]) -> Optional[str]:
    """Build deterministic SQL for supported, high-value question patterns."""
    from unified_api.services.governed_financial_queries import (
        build_governed_financial_sql,
    )

    financial_sql = build_governed_financial_sql(message)
    if financial_sql is not None:
        return financial_sql

    resolved = [
        entity for entity in resolved_entities
        if entity.get("status") == "resolved" and entity.get("company_id")
    ]
    resolved_drugs = [
        entity for entity in resolved_entities
        if entity.get("status") == "resolved" and entity.get("drug_id")
    ]
    year_match = re.search(r"\b(19|20)\d{2}\b", message)
    normalized = message.lower()

    if len(resolved_drugs) == 1:
        drug_id = int(resolved_drugs[0]["drug_id"])
        if "trial" in normalized:
            return (
                "SELECT trial.nct_id, trial.brief_title, trial.overall_status, "
                "trial.phases, trial.primary_completion_date, "
                "trial.lead_sponsor_name, trial.source_url, "
                "link.match_method, link.confidence, "
                "'clinicaltrials.gov_api_v2' AS source "
                "FROM clinical_trial_drugs link "
                "JOIN clinical_trials trial ON trial.nct_id = link.nct_id "
                f"WHERE link.drug_id = {drug_id} "
                "ORDER BY trial.primary_completion_date NULLS LAST, trial.nct_id "
                "LIMIT 20"
            )
        if any(term in normalized for term in ("target", "mechanism")):
            return (
                "SELECT drug.id AS drug_id, drug.name_display AS drug_name, "
                "link.chembl_id, target.ensembl_id, "
                "target.approved_symbol AS target_symbol, "
                "target.approved_name AS target_name, "
                "link.mechanism_of_action, link.action_type, "
                "link.source, link.source_version "
                "FROM public_drug_target_links link "
                "JOIN public_targets target ON target.ensembl_id = link.ensembl_id "
                "JOIN drugs drug ON drug.id = link.drug_id "
                f"WHERE link.drug_id = {drug_id} "
                "ORDER BY target.approved_symbol, link.chembl_id "
                "LIMIT 20"
            )
        if any(term in normalized for term in ("indication", "disease")):
            return (
                "SELECT drug.id AS drug_id, drug.name_display AS drug_name, "
                "link.chembl_id, disease.disease_id, disease.name AS disease_name, "
                "link.maximum_clinical_stage, link.source, link.source_version "
                "FROM public_drug_disease_links link "
                "JOIN public_diseases disease ON disease.disease_id = link.disease_id "
                "JOIN drugs drug ON drug.id = link.drug_id "
                f"WHERE link.drug_id = {drug_id} "
                "ORDER BY disease.name, link.chembl_id "
                "LIMIT 20"
            )

    target_match = re.search(
        r"\b(?:target(?:ing|s)?|inhibit(?:ing|s)?|against)\s+"
        r"([A-Za-z0-9-]{2,20})\b",
        message,
        re.IGNORECASE,
    )
    if target_match and any(term in normalized for term in ("drug", "asset")):
        target_symbol = target_match.group(1).upper()
        return (
            "SELECT target.ensembl_id, target.approved_symbol AS target_symbol, "
            "target.approved_name AS target_name, drug.id AS drug_id, "
            "drug.name_display AS drug_name, link.chembl_id, "
            "link.mechanism_of_action, link.action_type, "
            "link.source, link.source_version "
            "FROM public_targets target "
            "JOIN public_drug_target_links link "
            "ON link.ensembl_id = target.ensembl_id "
            "JOIN drugs drug ON drug.id = link.drug_id "
            f"WHERE UPPER(target.approved_symbol) = '{target_symbol}' "
            "ORDER BY drug.name_display, link.chembl_id "
            "LIMIT 20"
        )

    if "top 5" in normalized and "active acquirer" in normalized and "this year" in normalized:
        return (
            "SELECT c.id, c.name, COUNT(DISTINCT d.id) AS deal_count "
            "FROM deals d "
            "JOIN deal_companies dc ON dc.deal_id = d.id AND dc.role = 'Partner' "
            "JOIN companies c ON c.id = dc.company_id "
            "WHERE d.date_start >= DATE_TRUNC('year', CURRENT_DATE) "
            "GROUP BY c.id, c.name "
            "ORDER BY deal_count DESC, c.id "
            "LIMIT 5"
        )

    if "average deal size" in normalized and "oncology" in normalized:
        return (
            "SELECT AVG(f.total_projected_current_amount) AS average_deal_size_usd_millions, "
            "COUNT(*) AS disclosed_deal_count "
            "FROM deals d "
            "JOIN therapy_areas ta ON ta.id = d.therapy_area_id "
            "JOIN deal_finance_summary f ON f.deal_id = d.id "
            "WHERE ta.name = 'Cancer' "
            "AND f.total_projected_current_amount IS NOT NULL "
            "AND f.total_projected_current_currency = 'USD' "
            "AND f.total_projected_current_unit = 'Million' "
            "LIMIT 20"
        )

    if (
        "valuation range" in normalized
        and "oncology" in normalized
        and "m&a" in normalized
        and "2020" in normalized
        and "2025" in normalized
    ):
        return (
            "SELECT MIN(f.total_projected_current_amount) AS min_value_usd_millions, "
            "MAX(f.total_projected_current_amount) AS max_value_usd_millions, "
            "AVG(f.total_projected_current_amount) AS average_value_usd_millions, "
            "PERCENTILE_CONT(0.5) WITHIN GROUP "
            "(ORDER BY f.total_projected_current_amount) AS median_value_usd_millions, "
            "COUNT(*) AS disclosed_deal_count "
            "FROM deals d "
            "JOIN therapy_areas ta ON ta.id = d.therapy_area_id "
            "JOIN deal_finance_summary f ON f.deal_id = d.id "
            "WHERE ta.name = 'Cancer' "
            "AND d.agreement_type = 'Company - M&A (in whole or part)' "
            "AND d.date_start >= DATE '2020-01-01' "
            "AND d.date_start < DATE '2026-01-01' "
            "AND f.total_projected_current_amount IS NOT NULL "
            "AND f.total_projected_current_currency = 'USD' "
            "AND f.total_projected_current_unit = 'Million' "
            "LIMIT 20"
        )

    if "deal values trended" in normalized and "five years" in normalized:
        return (
            "SELECT EXTRACT(YEAR FROM d.date_start)::int AS year, "
            "COUNT(*) AS deal_count, "
            "COUNT(f.total_projected_current_amount) AS disclosed_deal_count, "
            "AVG(f.total_projected_current_amount) AS average_value_usd_millions, "
            "SUM(f.total_projected_current_amount) AS total_value_usd_millions "
            "FROM deals d "
            "LEFT JOIN deal_finance_summary f ON f.deal_id = d.id "
            "AND f.total_projected_current_currency = 'USD' "
            "AND f.total_projected_current_unit = 'Million' "
            "WHERE d.date_start >= CURRENT_DATE - INTERVAL '5 years' "
            "GROUP BY EXTRACT(YEAR FROM d.date_start)::int "
            "ORDER BY year"
        )

    if "percentage of 2024 deals" in normalized and "m&a" in normalized and "licens" in normalized:
        return (
            "WITH classified AS ("
            "SELECT CASE "
            "WHEN d.agreement_type = 'Company - M&A (in whole or part)' THEN 'M&A' "
            "WHEN d.agreement_type ILIKE '%License%' THEN 'Licensing' "
            "END AS category "
            "FROM deals d "
            "WHERE d.date_start >= DATE '2024-01-01' "
            "AND d.date_start < DATE '2025-01-01'"
            "), counts AS ("
            "SELECT category, COUNT(*) AS deal_count FROM classified "
            "WHERE category IS NOT NULL GROUP BY category"
            ") SELECT category, deal_count, "
            "ROUND(100.0 * deal_count / SUM(deal_count) OVER (), 2) AS percentage "
            "FROM counts ORDER BY category"
        )

    if "most actively acquiring oncology assets" in normalized:
        return (
            "SELECT c.id, c.name, COUNT(DISTINCT d.id) AS deal_count "
            "FROM deals d "
            "JOIN therapy_areas ta ON ta.id = d.therapy_area_id AND ta.name = 'Cancer' "
            "JOIN deal_companies dc ON dc.deal_id = d.id AND dc.role = 'Partner' "
            "JOIN companies c ON c.id = dc.company_id "
            "GROUP BY c.id, c.name "
            "ORDER BY deal_count DESC, c.id "
            "LIMIT 20"
        )

    if "top 20 largest pharma deals" in normalized:
        return (
            "SELECT d.id, d.title, d.status, d.agreement_type, "
            "d.date_start, f.total_projected_current_amount AS total_value_usd_millions "
            "FROM deals d "
            "JOIN deal_finance_summary f ON f.deal_id = d.id "
            "WHERE f.total_projected_current_amount IS NOT NULL "
            "AND f.total_projected_current_currency = 'USD' "
            "AND f.total_projected_current_unit = 'Million' "
            "ORDER BY f.total_projected_current_amount DESC, d.id "
            "LIMIT 20"
        )

    if "deal-activity heatmap" in normalized and "therapy area" in normalized:
        return (
            "SELECT ta.name AS therapy_area, COUNT(DISTINCT d.id) AS deal_count "
            "FROM deals d "
            "JOIN therapy_areas ta ON ta.id = d.therapy_area_id "
            "WHERE ta.name NOT IN ('Not Applicable', 'Unknown') "
            "GROUP BY ta.name "
            "ORDER BY deal_count DESC, ta.name "
            "LIMIT 20"
        )

    if "deal volume by geography" in normalized:
        return (
            "SELECT t.id AS territory_id, t.name AS territory_name, "
            "COUNT(DISTINCT dt.deal_id) AS deal_count "
            "FROM deal_territories dt "
            "JOIN territories t ON t.id = dt.territory_id "
            "GROUP BY t.id, t.name "
            "ORDER BY deal_count DESC, t.id "
            "LIMIT 20"
        )

    if (
        len(resolved) == 1
        and _is_deal_pattern_query(message)
        and "oncology" in normalized
    ):
        company_id = int(resolved[0]["company_id"])
        return (
            "SELECT COALESCE(d.agreement_type, 'Unknown') AS agreement_type, "
            "COUNT(DISTINCT d.id) AS deal_count, "
            "MIN(d.date_start) AS first_deal_date, "
            "MAX(d.date_start) AS latest_deal_date, "
            "COUNT(f.total_projected_current_amount) AS disclosed_value_count "
            "FROM deals d "
            "JOIN therapy_areas ta ON ta.id = d.therapy_area_id AND ta.name = 'Cancer' "
            "JOIN deal_companies dc ON dc.deal_id = d.id "
            "LEFT JOIN deal_finance_summary f ON f.deal_id = d.id "
            f"WHERE dc.company_id = {company_id} "
            "GROUP BY COALESCE(d.agreement_type, 'Unknown') "
            "ORDER BY deal_count DESC, agreement_type "
            "LIMIT 20"
        )

    if (
        len(resolved) == 1
        and year_match
        and "deal" in normalized
        and re.search(r"\bhow many\b|\bcount\b|\bnumber of\b", normalized)
    ):
        company_id = int(resolved[0]["company_id"])
        year = int(year_match.group(0))
        return (
            "SELECT COUNT(DISTINCT d.id) AS deal_count "
            "FROM deals d "
            "JOIN deal_companies dc ON dc.deal_id = d.id "
            f"WHERE dc.company_id = {company_id} "
            f"AND d.date_start >= DATE '{year}-01-01' "
            f"AND d.date_start < DATE '{year + 1}-01-01' "
            "LIMIT 20"
        )

    return None


async def _handle_rag_query(message: str) -> ChatResponse:
    """Handle RAG-based contract search queries."""
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session
    from unified_api.services.embed import get_embedding_provider
    from unified_api.services.llm import get_llm_service
    from unified_api.services.governed_metrics import build_citations

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
        citations=build_citations(
            "rag",
            [result.model_dump() for result in search_results],
        ),
    )


async def _handle_graph_query(message: str, llm_service) -> ChatResponse:
    """Handle graph-based relationship queries."""
    from unified_api.services.graph_sync import get_graph_sync_service
    from unified_api.services.governed_metrics import build_citations

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
            citations=build_citations("graph", data, query=message),
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
    resolved_entities: List[dict] = []
    citations: List[dict] = []


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
    from unified_api.services.governed_metrics import append_citation_section

    llm_service = get_llm_service()

    # Classify intent
    intent = await llm_service.classify_intent(request.message)

    # Route to appropriate handler and get raw data
    if intent in ["contract_search"]:
        raw_response = await _handle_rag_query(request.message)
        mode = "rag"
        data = [r.model_dump() for r in (raw_response.search_results or [])]
        sql_query = None
    elif intent in ["relationship", "company_compare"] and not _is_deal_pattern_query(
        request.message
    ):
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
    if not data and raw_response.response:
        synthesis = {
            "answer": raw_response.response,
            "confidence": {
                "data_completeness": "0 records retrieved",
                "sample_size": 0,
                "disclosure_rate": None,
                "evidence_status": "insufficient",
            },
            "follow_ups": [],
        }
    else:
        synthesis = await llm_service.synthesize_response(request.message, mode, data)

    confidence = dict(synthesis["confidence"])
    confidence["entity_resolution"] = raw_response.resolved_entities
    confidence["evidence_status"] = (
        "grounded" if data and raw_response.citations else confidence.get("evidence_status", "limited")
    )
    answer = append_citation_section(synthesis["answer"], raw_response.citations)

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
        answer=answer,
        intent=intent,
        confidence=confidence,
        data=data[:20],
        sql_query=sql_query,
        follow_ups=synthesis["follow_ups"],
        actions=actions,
        resolved_entities=raw_response.resolved_entities,
        citations=raw_response.citations,
    )
