"""
Agentic RAG service for multi-hop reasoning across data sources.
"""
from .models import (
    AgenticRagRequest,
    AgenticRagResponse,
    ReasoningStep,
    ToolResult,
    ToolType,
    ConversationState
)
from .tools import BaseTool, Neo4jTool, SQLTool, PgVectorTool

# Import agent only if langgraph is available
try:
    from .agent import AgenticRagAgent
    __all__ = [
        "AgenticRagRequest",
        "AgenticRagResponse",
        "ReasoningStep",
        "ToolResult",
        "ToolType",
        "ConversationState",
        "AgenticRagAgent",
        "BaseTool",
        "Neo4jTool",
        "SQLTool",
        "PgVectorTool"
    ]
except ImportError:
    __all__ = [
        "AgenticRagRequest",
        "AgenticRagResponse",
        "ReasoningStep",
        "ToolResult",
        "ToolType",
        "ConversationState",
        "BaseTool",
        "Neo4jTool",
        "SQLTool",
        "PgVectorTool"
    ]