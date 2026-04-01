"""
SSE streaming service for agentic RAG reasoning trace.

Formats and streams Server-Sent Events so the frontend can show
real-time reasoning: "Finding contract..." → "Searching Section 7..." → answer.
"""
import json
from typing import Any, AsyncGenerator, Callable, Optional

import structlog

logger = structlog.get_logger(__name__)


def format_sse_event(event_type: str, data: dict) -> str:
    """
    Format a Server-Sent Event string.

    Args:
        event_type: One of: thinking, tool_start, tool_result, reasoning_step, answer, error
        data: Event payload dict

    Returns:
        SSE-formatted string with event type and JSON data.
    """
    json_data = json.dumps(data, default=str)
    return f"event: {event_type}\ndata: {json_data}\n\n"


async def streaming_chat_generator(
    message: str,
    history: list,
    max_hops: int,
    chat_fn: Callable,
    tools: dict,
    llm: Any,
) -> AsyncGenerator[str, None]:
    """
    Async generator that yields SSE events for a streaming chat response.

    Wraps the non-streaming chat function and emits events at each stage:
    1. thinking — query analysis started
    2. tool_start — tool selected, query being executed
    3. reasoning_step — hop completed with result summary
    4. answer — final synthesized answer
    5. error — if something goes wrong

    Args:
        message: User's query
        history: Conversation history
        max_hops: Maximum reasoning hops
        chat_fn: Async function that runs the actual chat (returns AgenticRagResponse-like)
        tools: Available tools dict
        llm: LLM wrapper instance
    """
    # Emit thinking event
    yield format_sse_event("thinking", {
        "message": f"Analyzing query: {message[:100]}...",
    })

    try:
        # Run the actual chat
        result = await chat_fn(message, history, max_hops, tools, llm)

        # Emit reasoning steps
        if hasattr(result, "reasoning_steps"):
            for step in result.reasoning_steps:
                yield format_sse_event("reasoning_step", {
                    "hop": step.hop_number if hasattr(step, "hop_number") else 0,
                    "tool": step.tool_type.value if hasattr(step, "tool_type") else "unknown",
                    "thought": step.thought if hasattr(step, "thought") else "",
                    "result": step.result_summary if hasattr(step, "result_summary") else "",
                    "duration_ms": step.duration_ms if hasattr(step, "duration_ms") else None,
                })

        # Emit answer
        answer_text = result.answer if hasattr(result, "answer") else str(result)
        yield format_sse_event("answer", {
            "text": answer_text,
            "success": result.success if hasattr(result, "success") else True,
            "total_hops": result.total_hops if hasattr(result, "total_hops") else 0,
        })

    except Exception as e:
        logger.error("Streaming chat failed", error=str(e))
        yield format_sse_event("error", {
            "message": str(e),
        })
