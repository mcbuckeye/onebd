"""
TDD: Streaming reasoning trace tests.

Tests for SSE streaming of agentic RAG reasoning steps.
"""
import pytest
import json
from unittest.mock import MagicMock, AsyncMock, patch


class TestStreamEvent:
    """SSE event formatting."""

    def test_format_thinking_event(self):
        from unified_api.services.streaming import format_sse_event
        event = format_sse_event("thinking", {"message": "Analyzing query..."})
        assert "event: thinking" in event
        assert "Analyzing query" in event
        assert event.endswith("\n\n")

    def test_format_tool_start_event(self):
        from unified_api.services.streaming import format_sse_event
        event = format_sse_event("tool_start", {"tool": "pageindex", "query": "deal_id:150059"})
        assert "event: tool_start" in event
        assert "pageindex" in event

    def test_format_answer_event(self):
        from unified_api.services.streaming import format_sse_event
        event = format_sse_event("answer", {"text": "The upfront payment is $6M."})
        assert "event: answer" in event
        assert "$6M" in event

    def test_format_error_event(self):
        from unified_api.services.streaming import format_sse_event
        event = format_sse_event("error", {"message": "Tool failed"})
        assert "event: error" in event

    def test_format_reasoning_step_event(self):
        from unified_api.services.streaming import format_sse_event
        event = format_sse_event("reasoning_step", {
            "hop": 1,
            "tool": "sql",
            "thought": "Finding the deal...",
            "result": "Found deal 150059",
        })
        assert "event: reasoning_step" in event
        assert "Finding the deal" in event


class TestStreamingChatGenerator:
    """Async generator for streaming chat responses."""

    @pytest.mark.asyncio
    async def test_generator_yields_thinking_first(self):
        from unified_api.services.streaming import streaming_chat_generator

        # Mock the non-streaming chat function
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.answer = "The answer is 42."
        mock_result.reasoning_steps = []
        mock_result.total_hops = 0

        async def mock_chat(message, history, max_hops, tools, llm):
            return mock_result

        events = []
        async for event in streaming_chat_generator(
            message="test query",
            history=[],
            max_hops=5,
            chat_fn=mock_chat,
            tools={},
            llm=None,
        ):
            events.append(event)

        # Should have at least thinking + answer events
        assert len(events) >= 2
        assert "thinking" in events[0]
        assert "answer" in events[-1]

    @pytest.mark.asyncio
    async def test_generator_yields_error_on_failure(self):
        from unified_api.services.streaming import streaming_chat_generator

        async def mock_chat(message, history, max_hops, tools, llm):
            raise Exception("LLM crashed")

        events = []
        async for event in streaming_chat_generator(
            message="test query",
            history=[],
            max_hops=5,
            chat_fn=mock_chat,
            tools={},
            llm=None,
        ):
            events.append(event)

        # Should have error event
        assert any("error" in e for e in events)
