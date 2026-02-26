"""
Pydantic models for Agentic RAG.
Defines request/response schemas and internal state management.
"""
from typing import List, Dict, Any, Optional, Literal
from enum import Enum
from pydantic import BaseModel, Field


class ToolType(str, Enum):
    """Available tool types for the agent."""
    NEO4J = "neo4j"
    SQL = "sql"
    PGVECTOR = "pgvector"
    SYNTHESIZE = "synthesize"  # Final answer generation


class AgenticRagRequest(BaseModel):
    """Request body for agentic RAG chat endpoint."""
    message: str = Field(..., description="User's natural language query")
    history: List[Dict[str, str]] = Field(
        default_factory=list,
        description="Previous conversation messages"
    )
    max_hops: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Maximum reasoning hops before stopping"
    )


class AttemptDetail(BaseModel):
    """A single attempt within a reasoning step (including retries)."""
    attempt_number: int = Field(..., ge=1, description="Attempt number (1 = first try)")
    query: str = Field(..., description="Query that was tried")
    success: bool = Field(..., description="Whether this attempt succeeded")
    error: Optional[str] = Field(default=None, description="Error message if failed")
    row_count: int = Field(default=0, description="Rows returned (if success)")
    was_corrected: bool = Field(default=False, description="Whether this was a self-corrected query")
    correction_explanation: Optional[str] = Field(default=None, description="Why the query was corrected")
    duration_ms: Optional[int] = Field(default=None, description="Time this attempt took")


class ReasoningStep(BaseModel):
    """A single step in the agent's reasoning process."""
    hop_number: int = Field(..., ge=1, description="Which hop this is")
    thought: str = Field(..., description="Agent's thought process")
    tool_type: ToolType = Field(..., description="Tool selected")
    query: str = Field(..., description="Query sent to tool")
    result_summary: str = Field(..., description="Brief summary of result")
    retry_count: int = Field(default=0, ge=0, description="Number of retries")
    error: Optional[str] = Field(default=None, description="Error if tool failed - shows final error after all retries")
    duration_ms: Optional[int] = Field(default=None, description="Execution time")
    attempts: List[AttemptDetail] = Field(default_factory=list, description="All attempts including failures and retries")


class ToolResult(BaseModel):
    """Result from a tool execution."""
    success: bool = Field(..., description="Whether execution succeeded")
    data: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Result data rows"
    )
    error: Optional[str] = Field(default=None, description="Error message if failed")
    row_count: int = Field(default=0, description="Number of rows returned")
    query_executed: Optional[str] = Field(default=None, description="Actual query run")


class AgenticRagResponse(BaseModel):
    """Response from agentic RAG chat endpoint."""
    success: bool = Field(..., description="Whether query was processed successfully")
    answer: str = Field(..., description="Final synthesized answer")
    partial: bool = Field(
        default=False,
        description="True if max hops reached before complete answer"
    )
    reasoning_steps: List[ReasoningStep] = Field(
        default_factory=list,
        description="Full reasoning trace"
    )
    total_hops: int = Field(..., description="Number of hops executed")
    total_tokens: Optional[int] = Field(default=None, description="Token usage")
    latency_ms: Optional[int] = Field(default=None, description="Total latency")


class ConversationState(BaseModel):
    """Internal state for a conversation with the agent."""
    original_query: str = Field(..., description="User's original question")
    history: List[Dict[str, str]] = Field(default_factory=list)
    reasoning_steps: List[ReasoningStep] = Field(default_factory=list)
    current_hop: int = Field(default=0, ge=0)
    max_hops: int = Field(default=5, ge=1, le=10)
    is_complete: bool = Field(default=False)
    final_answer: Optional[str] = Field(default=None)
    accumulated_data: Dict[str, Any] = Field(default_factory=dict)

    def add_step(self, step: ReasoningStep) -> None:
        """Add a reasoning step and increment hop counter."""
        self.reasoning_steps.append(step)
        self.current_hop += 1

    def can_continue(self) -> bool:
        """Check if agent can continue reasoning."""
        return not self.is_complete and self.current_hop < self.max_hops

    def mark_complete(self, answer: str) -> None:
        """Mark conversation as complete with final answer."""
        self.is_complete = True
        self.final_answer = answer

    def get_context_for_llm(self) -> str:
        """Format current state for LLM context window."""
        context = f"Original query: {self.original_query}\n\n"
        if self.reasoning_steps:
            context += "Previous steps:\n"
            for step in self.reasoning_steps:
                context += f"  {step.hop_number}. {step.tool_type}: {step.result_summary}\n"
        return context


class StreamingEvent(BaseModel):
    """A single event in the streaming response."""
    type: Literal["thinking", "tool_start", "tool_result", "reasoning_step", "answer", "error"]
    data: Dict[str, Any]
    timestamp: Optional[float] = Field(default=None)


class ToolSelection(BaseModel):
    """LLM's selection of which tool to use."""
    thought: str = Field(..., description="Reasoning for tool selection")
    tool: Optional[ToolType] = Field(default=None, description="Selected tool (null if synthesizing)")
    query: Optional[str] = Field(default=None, description="Query for the tool (null if synthesizing)")
    synthesize: bool = Field(default=False, description="Whether to synthesize final answer")
