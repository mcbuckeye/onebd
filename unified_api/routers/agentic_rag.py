"""
Agentic RAG router for multi-hop reasoning queries.
Routes to LangGraph agent with Neo4j, SQL, and pgvector tools.
"""
from typing import Optional, List
import os
import structlog
import json
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import APIRouter, HTTPException, Depends, Request
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
from unified_api.services.agentic_rag import (
    AgenticRagRequest,
    AgenticRagResponse,
    ReasoningStep,
    ToolType
)
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
    uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")

    if not password:
        logger.warning("Neo4j password not set, tool unavailable")
        return None

    return Neo4jTool(uri=uri, username=user, password=password)


def _get_sql_tool() -> Optional[SQLTool]:
    """Create SQL tool from database session."""
    # This will be injected via dependency
    # For now return None - real implementation uses Depends
    return None


def _get_pgvector_tool() -> Optional[PgVectorTool]:
    """Create pgvector tool from database session."""
    # Will be injected via dependency
    return None


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

    try:
        # Initialize tools
        neo4j_tool = _get_neo4j_tool()
        if neo4j_tool:
            tools[ToolType.NEO4J] = neo4j_tool

        # TODO: Get SQL and pgvector tools from session factory
        # For now these are placeholders
        # tools[ToolType.SQL] = ...
        # tools[ToolType.PGVECTOR] = ...

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
                        duration_ms=s.duration_ms
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
                if result.success:
                    answer_prompt = f"""Based on this data, answer the user's question:
Question: {request.message}
Data: {json.dumps(result.data[:10], default=str)}

Provide a concise answer."""
                    answer_response = await llm.ainvoke(answer_prompt)
                    answer = answer_response.content.strip()
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
        # Cleanup
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
    """
    # TODO: Implement streaming using agent.run_streaming()
    # For now, return error indicating not implemented

    raise HTTPException(
        status_code=501,
        detail="Streaming not yet implemented. Use /chat endpoint."
    )


@router.get("/health")
async def agentic_rag_health():
    """Check health of Agentic RAG service and available tools."""
    tools_status = {}

    # Check Neo4j
    neo4j_tool = _get_neo4j_tool()
    if neo4j_tool:
        try:
            available = await neo4j_tool.is_available()
            tools_status["neo4j"] = "available" if available else "unavailable"
        except Exception:
            tools_status["neo4j"] = "error"
    else:
        tools_status["neo4j"] = "not_configured"

    return {
        "status": "healthy" if any(t == "available" for t in tools_status.values()) else "degraded",
        "tools": tools_status,
        "timestamp": datetime.utcnow().isoformat()
    }