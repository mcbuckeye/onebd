"""
Agentic RAG router for multi-hop reasoning queries.
Routes to LangGraph agent with Neo4j, SQL, and pgvector tools.
"""
from typing import Optional, List
import os
import structlog
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Langfuse observability
from langfuse import Langfuse
from langfuse.decorators import observe

# Agent imports
from unified_api.services.agentic_rag import (
    AgenticRagRequest,
    AgenticRagResponse,
    ReasoningStep,
    AgenticRagAgent,
    ToolType
)
from unified_api.services.agentic_rag.tools import Neo4jTool, SQLTool, PgVectorTool

# Auth (reuse from existing auth)
from unified_api.routers.auth import get_current_user

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/agentic-rag", tags=["agentic-rag"])

# Initialize Langfuse
langfuse = Langfuse(
    public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
    secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
    host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
) if os.getenv("LANGFUSE_PUBLIC_KEY") else None


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
@observe()
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
    trace = None

    # Start Langfuse trace
    if langfuse:
        trace = langfuse.trace(
            name="agentic_rag_chat",
            user_id=current_user.get("email", "anonymous"),
            metadata={
                "query": request.message,
                "max_hops": request.max_hops
            }
        )

    try:
        # Initialize tools
        tools = {}

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

        # TODO: Initialize LLM (Azure OpenAI)
        # This depends on how you configure LLMs in your project
        # llm = ...

        # For now, return placeholder response
        # Real implementation would create AgenticRagAgent and call run()

        latency_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)

        response = AgenticRagChatResponse(
            success=True,
            answer=f"Query received: {request.message}. Agentic RAG implementation in progress.",
            partial=False,
            reasoning_steps=[],
            total_hops=0,
            latency_ms=latency_ms
        )

        # Update Langfuse trace
        if trace:
            trace.update(
                output={"answer": response.answer},
                metadata={"latency_ms": latency_ms}
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
        if neo4j_tool := tools.get(ToolType.NEO4J):
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