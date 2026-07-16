"""
Agentic RAG router for multi-hop reasoning queries.
Routes to LangGraph agent with Neo4j, SQL, and pgvector tools.
"""
from typing import Optional, List
import os
import structlog
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from openai import AsyncOpenAI

# Langfuse observability
try:
    from langfuse import Langfuse
    from langfuse.decorators import observe
    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    Langfuse = None
    def observe():
        return lambda f: f

# Agent imports
from unified_api.services.agentic_rag import ToolType
from unified_api.services.agentic_rag.tools import Neo4jTool, SQLTool, PgVectorTool
from unified_api.config import settings

# Auth (reuse from existing auth)
from unified_api.routers.auth import get_current_user

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/agentic-rag", tags=["agentic-rag"])

# Initialize Langfuse
if LANGFUSE_AVAILABLE and os.getenv("LANGFUSE_PUBLIC_KEY"):
    langfuse = Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
        host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
    )
else:
    langfuse = None

# Initialize OpenAI client
openai_client = None
if settings.openai_api_key:
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    logger.info("OpenAI client initialized", model=settings.openai_model)
else:
    logger.warning("OpenAI API key not set - agentic RAG will be unavailable")


class AgenticRagChatRequest(BaseModel):
    """Request body for agentic RAG chat."""
    message: str = Field(..., description="User's natural language query")
    history: List[dict] = Field(default_factory=list, description="Conversation history")
    max_hops: int = Field(default=5, ge=1, le=10, description="Max reasoning hops")
    stream: bool = Field(default=False, description="Stream response with reasoning trace")


class AttemptResponse(BaseModel):
    """A single attempt within a reasoning step."""
    attempt_number: int
    query: str
    success: bool
    error: Optional[str] = None
    row_count: int = 0
    was_corrected: bool = False
    correction_explanation: Optional[str] = None
    duration_ms: Optional[int] = None


class ReasoningStepResponse(BaseModel):
    """A single reasoning step in the response."""
    hop_number: int
    thought: str
    tool_type: str
    query: str
    result_summary: str
    retry_count: int = 0
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    attempts: List[AttemptResponse] = Field(default_factory=list, description="All attempts including failures")


class AgenticRagChatResponse(BaseModel):
    """Response from agentic RAG chat endpoint."""
    success: bool
    answer: str
    partial: bool = False
    reasoning_steps: List[ReasoningStepResponse] = []
    total_hops: int
    latency_ms: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)


def _get_neo4j_tool() -> Optional[Neo4jTool]:
    """Create Neo4j tool from environment."""
    from unified_api.config import settings

    if not settings.neo4j_password:
        logger.warning("Neo4j password not set, tool unavailable")
        return None

    return Neo4jTool(
        uri=settings.neo4j_uri,
        username=settings.neo4j_user,
        password=settings.neo4j_password
    )


def _get_sql_tool() -> Optional[SQLTool]:
    """Create SQL tool for Cortellis database."""
    from unified_api.services.database import get_cortellis_session_factory

    def session_factory():
        factory = get_cortellis_session_factory()
        return factory()

    return SQLTool(session_factory=session_factory)


def _get_pgvector_tool() -> Optional[PgVectorTool]:
    """Create pgvector tool for Edgar database."""
    from unified_api.services.database import get_edgar_source_session_factory

    def session_factory():
        factory = get_edgar_source_session_factory()
        return factory()

    return PgVectorTool(session_factory=session_factory)


def _get_pageindex_tool():
    """Create PageIndex tool for contract deep-reading."""
    from unified_api.services.agentic_rag.tools import PageIndexTool
    from unified_api.services.database import get_cortellis_session_factory

    if not settings.openai_api_key:
        logger.warning("OpenAI API key not set, PageIndex tool unavailable")
        return None

    def session_factory():
        factory = get_cortellis_session_factory()
        return factory()

    return PageIndexTool(
        session_factory=session_factory,
        openai_api_key=settings.openai_api_key,
        model=settings.openai_model or "gpt-4o-2024-11-20",
    )


def _get_evidence_tool():
    """Create Evidence tool for clinical efficacy queries."""
    from unified_api.services.agentic_rag.tools import EvidenceTool
    from unified_api.services.database import get_cortellis_session_factory

    if not settings.openai_api_key:
        logger.warning("OpenAI API key not set, Evidence tool unavailable")
        return None

    def session_factory():
        factory = get_cortellis_session_factory()
        return factory()

    return EvidenceTool(
        session_factory=session_factory,
        openai_api_key=settings.openai_api_key,
        model=settings.openai_model or "gpt-4o-2024-11-20",
    )


async def _governed_agentic_response(
    message: str,
    *,
    started_at: datetime,
) -> AgenticRagChatResponse | None:
    """Use the governed relational query library for supported metrics.

    Agentic RAG previously asked the model to rediscover the Cortellis schema
    for even the product's own examples.  That produced title-only oncology
    matching and treated a JSON blob as financial data.  Shared governed SQL
    keeps supported questions consistent with Ask and exposes the exact query
    in the reasoning trace.
    """
    from unified_api.routers.chat import _build_governed_sql, _governed_synthesis

    query = _build_governed_sql(message, [])
    if query is None:
        return None

    tool = _get_sql_tool()
    if tool is None:
        return None
    result = await tool.execute(query)
    latency_ms = int((datetime.utcnow() - started_at).total_seconds() * 1000)
    if not result.success:
        return AgenticRagChatResponse(
            success=False,
            answer=(
                "The governed Cortellis query could not be completed. "
                "No factual answer was generated."
            ),
            partial=True,
            reasoning_steps=[ReasoningStepResponse(
                hop_number=1,
                thought="Run a governed structured-data query",
                tool_type="sql",
                query=query,
                result_summary="Governed SQL failed",
                error=result.error,
            )],
            total_hops=1,
            latency_ms=latency_ms,
        )

    rows = result.data or []
    synthesis = _governed_synthesis(message, rows)
    if synthesis is not None:
        answer = synthesis["answer"]
    elif rows:
        answer = (
            f"The governed query returned {len(rows)} structured records. "
            "Open the reasoning step to review the exact query."
        )
    else:
        answer = (
            "No supporting structured Cortellis records matched this question. "
            "This is a bounded database result, not proof that no such activity exists."
        )

    return AgenticRagChatResponse(
        success=True,
        answer=answer,
        partial=False,
        reasoning_steps=[ReasoningStepResponse(
            hop_number=1,
            thought=(
                "Use the same governed relational definition as Ask so therapy "
                "area, modality, and disclosed financial values are matched in "
                "their structured tables."
            ),
            tool_type="sql",
            query=query,
            result_summary=f"Retrieved {len(rows)} governed records",
            duration_ms=latency_ms,
            attempts=[AttemptResponse(
                attempt_number=1,
                query=query,
                success=True,
                row_count=len(rows),
                duration_ms=latency_ms,
            )],
        )],
        total_hops=1,
        latency_ms=latency_ms,
    )


@router.post("/chat", response_model=AgenticRagChatResponse)
async def agentic_rag_chat(
    request: AgenticRagChatRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Process a natural language query using multi-hop agentic RAG.

    The agent will:
    1. Analyze the query
    2. Select appropriate tools (Neo4j, SQL, pgvector)
    3. Execute multi-hop reasoning
    4. Synthesize final answer with citations
    """
    start_time = datetime.utcnow()

    governed = await _governed_agentic_response(
        request.message,
        started_at=start_time,
    )
    if governed is not None:
        return governed

    # Check OpenAI available
    if not openai_client:
        raise HTTPException(
            status_code=503,
            detail="Agentic RAG unavailable - OpenAI API key not configured"
        )

    # Start Langfuse trace
    trace = None
    if langfuse:
        trace = langfuse.trace(
            name="agentic_rag_chat",
            user_id=current_user.get("email", "anonymous"),
            metadata={
                "query": request.message,
                "max_hops": request.max_hops
            }
        )

    tools = {}
    neo4j_tool = None
    sql_tool = None
    pgvector_tool = None

    try:
        # Initialize tools
        neo4j_tool = _get_neo4j_tool()
        if neo4j_tool:
            tools[ToolType.NEO4J] = neo4j_tool

        sql_tool = _get_sql_tool()
        if sql_tool:
            tools[ToolType.SQL] = sql_tool

        pgvector_tool = _get_pgvector_tool()
        if pgvector_tool:
            tools[ToolType.PGVECTOR] = pgvector_tool

        pageindex_tool = _get_pageindex_tool()
        if pageindex_tool:
            tools[ToolType.PAGEINDEX] = pageindex_tool

        evidence_tool = _get_evidence_tool()
        if evidence_tool:
            tools[ToolType.EVIDENCE] = evidence_tool

        if not tools:
            raise HTTPException(
                status_code=503,
                detail="No data sources available. Check service configuration."
            )

        # Create LLM wrapper for LangGraph
        class OpenAIWrapper:
            """Wrapper to make OpenAI client compatible with LangGraph expectations."""
            def __init__(self, client, model):
                self.client = client
                self.model = model

            async def ainvoke(self, prompt):
                """Invoke LLM with a prompt string."""
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    max_tokens=1000
                )
                return response.choices[0].message

            async def astream(self, prompt):
                """Stream LLM response."""
                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0,
                    stream=True
                )
                async for chunk in stream:
                    content = chunk.choices[0].delta.content
                    if content:
                        yield content

        llm = OpenAIWrapper(openai_client, settings.openai_model)

        # Try to use LangGraph agent, fall back to simple implementation
        try:
            from unified_api.services.agentic_rag.agent import AgenticRagAgent

            agent = AgenticRagAgent(
                llm=llm,
                tools=tools,
                max_hops=request.max_hops
            )

            result = await agent.run(request.message, request.history)

            # Log for debugging
            if result.reasoning_steps:
                for step in result.reasoning_steps:
                    logger.info(f"Agent step {step.hop_number}: {step.tool_type.value} - {step.result_summary}")

            latency_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

            response = AgenticRagChatResponse(
                success=result.success,
                answer=result.answer,
                partial=result.partial,
                reasoning_steps=[
                    ReasoningStepResponse(
                        hop_number=s.hop_number,
                        thought=s.thought,
                        tool_type=s.tool_type.value,
                        query=s.query,
                        result_summary=s.result_summary,
                        retry_count=s.retry_count,
                        error=s.error,
                        duration_ms=s.duration_ms,
                        attempts=[
                            AttemptResponse(
                                attempt_number=a.attempt_number,
                                query=a.query,
                                success=a.success,
                                error=a.error,
                                row_count=a.row_count,
                                was_corrected=a.was_corrected,
                                correction_explanation=a.correction_explanation,
                                duration_ms=a.duration_ms
                            ) for a in (s.attempts or [])
                        ]
                    ) for s in result.reasoning_steps
                ],
                total_hops=result.total_hops,
                latency_ms=latency_ms
            )

        except ImportError:
            # LangGraph not available - use simple direct approach
            logger.warning("LangGraph not available, using simple implementation")

            # Simple single-hop for now
            tool = tools.get(ToolType.NEO4J)
            if tool:
                # Generate query using LLM
                prompt = f"""Generate a Cypher query for Neo4j to answer:
{request.message}

Available schema:
- Deal nodes with properties: id, title, area, indication, phase, deal_type
- Company nodes with: id, name, type
- Relationships: (Deal)-[:INVOLVES]->(Company)

Return ONLY the Cypher query, no explanation."""

                llm_response = await llm.ainvoke(prompt)
                cypher_query = llm_response.content.strip()

                # Remove markdown if present
                if cypher_query.startswith("```"):
                    lines = cypher_query.split("\n")
                    cypher_query = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
                    cypher_query = cypher_query.strip()

                result = await tool.execute(cypher_query)

                # Synthesize answer
                if result.success and result.row_count > 0 and result.data:
                    # Extract readable deal info from Neo4j node data
                    deals = []
                    for row in result.data[:10]:
                        # Neo4j returns nodes as dicts with properties
                        deal_info = {}
                        try:
                            if 'd' in row and isinstance(row['d'], dict):
                                node = row['d']
                                deal_info['title'] = node.get('title', 'N/A')[:200]  # Truncate long titles
                                deal_info['status'] = node.get('status', 'N/A')
                                deal_info['deal_type'] = node.get('deal_type', 'N/A')
                                deal_info['announced'] = node.get('announced_at', 'N/A')[:10]  # Just date
                            else:
                                deal_info = {k: str(v)[:200] for k, v in row.items()}
                            deals.append(deal_info)
                        except Exception:
                            deals.append({"info": str(row)[:200]})

                    answer_prompt = f"""Based on this deal data, answer concisely:

Question: {request.message}

Found {result.row_count} deal(s):
{chr(10).join([f"- {d.get('title', 'Unknown')} ({d.get('status', 'N/A')}, {d.get('announced', 'N/A')})" for d in deals])}

Summarize the key findings briefly."""

                    answer_response = await llm.ainvoke(answer_prompt)
                    answer = answer_response.content.strip()
                elif result.success:
                    answer = f"No deals found matching '{request.message}'. The database has 145,000+ deals - try different keywords like 'cancer', 'tumor', or specific company names."
                else:
                    answer = f"Query failed: {result.error}"

                latency_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

                response = AgenticRagChatResponse(
                    success=result.success,
                    answer=answer,
                    partial=False,
                    reasoning_steps=[
                        ReasoningStepResponse(
                            hop_number=1,
                            thought="Querying Neo4j graph database",
                            tool_type="neo4j",
                            query=cypher_query[:200],
                            result_summary=f"{'Success' if result.success else 'Failed'}: {result.row_count} rows",
                            retry_count=0,
                            error=result.error
                        )
                    ],
                    total_hops=1,
                    latency_ms=latency_ms
                )
            else:
                raise HTTPException(status_code=503, detail="No tools available")

        # Update Langfuse trace
        if trace:
            trace.update(
                output={"answer": response.answer, "hops": response.total_hops},
                metadata={"latency_ms": response.latency_ms}
            )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Agentic RAG chat failed", error=str(e))

        if trace:
            trace.update(
                output={"error": str(e)},
                status_message="error"
            )

        raise HTTPException(
            status_code=500,
            detail=f"Agentic RAG processing failed: {str(e)}"
        )
    finally:
        # Cleanup sessions
        if neo4j_tool:
            await neo4j_tool.close()


@router.post("/chat/stream")
async def agentic_rag_chat_stream(
    request: AgenticRagChatRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Stream agentic RAG response with real-time reasoning trace.

    Returns SSE (Server-Sent Events) with:
    - thinking: Agent initialization
    - reasoning_step: Each hop with thought, tool, result
    - answer: Final synthesized answer
    - error: If something goes wrong
    """
    from unified_api.services.streaming import streaming_chat_generator

    if not openai_client:
        raise HTTPException(
            status_code=503,
            detail="Agentic RAG unavailable - OpenAI API key not configured"
        )

    # Build tools (same as non-streaming endpoint)
    tools = {}
    neo4j_tool = _get_neo4j_tool()
    if neo4j_tool:
        tools[ToolType.NEO4J] = neo4j_tool
    sql_tool = _get_sql_tool()
    if sql_tool:
        tools[ToolType.SQL] = sql_tool
    pgvector_tool = _get_pgvector_tool()
    if pgvector_tool:
        tools[ToolType.PGVECTOR] = pgvector_tool
    pageindex_tool = _get_pageindex_tool()
    if pageindex_tool:
        tools[ToolType.PAGEINDEX] = pageindex_tool
    evidence_tool = _get_evidence_tool()
    if evidence_tool:
        tools[ToolType.EVIDENCE] = evidence_tool

    # Create LLM wrapper
    class OpenAIWrapper:
        def __init__(self, client, model):
            self.client = client
            self.model = model
        async def ainvoke(self, prompt):
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0, max_tokens=1000
            )
            return response.choices[0].message

    llm = OpenAIWrapper(openai_client, settings.openai_model)

    # Streaming chat function that wraps the agent
    async def run_agent_chat(message, history, max_hops, tools, llm):
        try:
            from unified_api.services.agentic_rag.agent import AgenticRagAgent
            agent = AgenticRagAgent(llm=llm, tools=tools, max_hops=max_hops)
            return await agent.run(message, history)
        except ImportError:
            # LangGraph not available — return simple error
            from unified_api.services.agentic_rag.models import AgenticRagResponse
            return AgenticRagResponse(
                success=False,
                answer="Streaming requires LangGraph agent. Use /chat endpoint.",
                total_hops=0,
            )

    return StreamingResponse(
        streaming_chat_generator(
            message=request.message,
            history=request.history,
            max_hops=request.max_hops,
            chat_fn=run_agent_chat,
            tools=tools,
            llm=llm,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/health")
async def agentic_rag_health():
    """Check health of Agentic RAG service and available tools."""
    tools_status = {}

    # Check Neo4j
    neo4j_tool = _get_neo4j_tool()
    if neo4j_tool:
        try:
            # Neo4jTool has async is_available
            available = await neo4j_tool.is_available()
            tools_status["neo4j"] = "available" if available else "unavailable"
        except Exception as e:
            logger.warning("Neo4j health check failed", error=str(e))
            tools_status["neo4j"] = "error"
    else:
        tools_status["neo4j"] = "not_configured"

    return {
        "status": "healthy" if any(t == "available" for t in tools_status.values()) else "degraded",
        "tools": tools_status,
        "timestamp": datetime.utcnow().isoformat()
    }
