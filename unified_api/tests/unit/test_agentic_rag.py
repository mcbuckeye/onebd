"""
Unit tests for Agentic RAG service.
Tests the agent logic, tool interfaces, and state management.
"""
import json
import pytest
from unittest.mock import Mock, AsyncMock

from unified_api.services.agentic_rag.models import (
    AgenticRagRequest,
    ReasoningStep,
    ToolResult,
    ToolType,
    ConversationState
)


class TestModels:
    """Test Pydantic models."""

    def test_agentic_rag_request_valid(self):
        """Test valid request creation."""
        request = AgenticRagRequest(
            message="Find deals related to BTK inhibitors",
            max_hops=5
        )
        assert request.message == "Find deals related to BTK inhibitors"
        assert request.max_hops == 5
        assert request.history == []

    def test_agentic_rag_request_with_history(self):
        """Test request with conversation history."""
        history = [
            {"role": "user", "content": "What deals do we have?"},
            {"role": "assistant", "content": "Found 5 deals."}
        ]
        request = AgenticRagRequest(
            message="Which ones are in Phase 3?",
            history=history,
            max_hops=3
        )
        assert len(request.history) == 2
        assert request.max_hops == 3

    def test_reasoning_step_creation(self):
        """Test reasoning step model."""
        step = ReasoningStep(
            hop_number=1,
            thought="Need to query Neo4j for deals",
            tool_type=ToolType.NEO4J,
            query="MATCH (d:Deal) WHERE d.area CONTAINS 'Oncology' RETURN d",
            result_summary="Found 12 deals"
        )
        assert step.hop_number == 1
        assert step.tool_type == ToolType.NEO4J
        assert step.retry_count == 0

    def test_tool_result_success(self):
        """Test successful tool result."""
        result = ToolResult(
            success=True,
            data=[{"deal_id": 1, "title": "Deal A"}],
            row_count=1
        )
        assert result.success is True
        assert result.error is None
        assert result.row_count == 1

    def test_tool_result_error(self):
        """Test error tool result."""
        result = ToolResult(
            success=False,
            error="Connection refused",
            data=None
        )
        assert result.success is False
        assert result.error == "Connection refused"
        assert result.row_count == 0

    def test_conversation_state_initial(self):
        """Test initial conversation state."""
        state = ConversationState(
            original_query="Find BTK deals"
        )
        assert state.current_hop == 0
        assert state.max_hops == 5
        assert state.is_complete is False
        assert len(state.reasoning_steps) == 0

    def test_conversation_state_add_step(self):
        """Test adding reasoning steps."""
        state = ConversationState(original_query="Test")
        step = ReasoningStep(
            hop_number=1,
            thought="Querying",
            tool_type=ToolType.SQL,
            query="SELECT * FROM deals",
            result_summary="Found 5"
        )
        state.add_step(step)
        assert state.current_hop == 1
        assert len(state.reasoning_steps) == 1

    def test_conversation_context_includes_actual_rows(self):
        state = ConversationState(
            original_query="Who partnered with Acme?",
            accumulated_data={
                "hop_1": {
                    "source": "neo4j",
                    "row_count": 1,
                    "rows": [{"company": "Acme Bio", "deal_id": 42}],
                }
            },
        )

        context = state.get_context_for_llm()

        assert "Acme Bio" in context
        assert '"deal_id": 42' in context


class TestToolInterfaces:
    """Test tool base classes and implementations."""

    @pytest.fixture
    def mock_neo4j_driver(self):
        """Mock Neo4j driver."""
        return Mock()

    @pytest.mark.asyncio
    async def test_neo4j_tool_success(self, mock_neo4j_driver):
        """Test Neo4j tool successful execution."""
        from unified_api.services.agentic_rag.tools.neo4j_tool import Neo4jTool

        mock_record = {"deal_id": 1, "title": "Test Deal"}
        mock_result = AsyncMock()
        mock_result.data.return_value = [mock_record]
        mock_session = AsyncMock()
        mock_session.run.return_value = mock_result
        session_context = AsyncMock()
        session_context.__aenter__.return_value = mock_session
        mock_neo4j_driver.session.return_value = session_context

        tool = Neo4jTool(driver=mock_neo4j_driver)
        result = await tool.execute(
            query="MATCH (d:Deal) RETURN d.id, d.title LIMIT 1"
        )

        assert result.success is True
        assert result.row_count == 1
        assert len(result.data) == 1

    @pytest.mark.asyncio
    async def test_neo4j_tool_error_retry(self, mock_neo4j_driver):
        """Test Neo4j tool retries on error."""
        from unified_api.services.agentic_rag.tools.neo4j_tool import Neo4jTool

        mock_session = AsyncMock()
        mock_session.run.side_effect = Exception("Connection lost")
        session_context = AsyncMock()
        session_context.__aenter__.return_value = mock_session
        mock_neo4j_driver.session.return_value = session_context

        tool = Neo4jTool(driver=mock_neo4j_driver, max_retries=2)
        result = await tool.execute(query="MATCH (n) RETURN n")

        assert result.success is False
        assert "Connection lost" in result.error
        assert mock_session.run.call_count == 3  # initial + 2 retries

    @pytest.mark.asyncio
    async def test_sql_tool_success(self):
        """Test SQL tool successful execution."""
        from unified_api.services.agentic_rag.tools.sql_tool import SQLTool

        mock_session = Mock()
        mock_result = Mock()
        mock_result.mappings.return_value.all.return_value = [
            {"deal_id": 1, "deal_name": "Test Deal"}
        ]
        mock_session.execute.return_value = mock_result

        tool = SQLTool(session_factory=lambda: mock_session)
        result = await tool.execute(
            query="SELECT id, name FROM deals LIMIT 1"
        )

        assert result.success is True
        assert result.row_count == 1

    @pytest.mark.asyncio
    async def test_pgvector_tool_success(self):
        """Test pgvector tool successful execution."""
        from unified_api.services.agentic_rag.tools.pgvector_tool import PgVectorTool

        mock_session = Mock()
        mock_result = Mock()
        mock_result.mappings.return_value.all.return_value = [
            {
                "contract_id": 1,
                "content": "This agreement covers...",
                "similarity": 0.89
            }
        ]
        mock_session.execute.return_value = mock_result

        tool = PgVectorTool(session_factory=lambda: mock_session)
        result = await tool.execute(
            query="BTK inhibitor licensing terms"
        )

        assert result.success is True
        assert result.row_count == 1
        assert "similarity" in result.data[0]


class TestAgentLogic:
    """Test the LangGraph agent orchestration."""

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM for testing."""
        mock = Mock()
        mock.ainvoke = AsyncMock()
        return mock

    @pytest.fixture
    def mock_tools(self):
        """Mock all tools."""
        tools = {}
        for tool_type in (ToolType.NEO4J, ToolType.SQL, ToolType.PGVECTOR):
            tool = Mock()
            tool.is_available.return_value = True
            tool.get_schema_description.return_value = f"{tool_type.value} schema"
            tool.execute = AsyncMock()
            tools[tool_type] = tool
        return tools

    @pytest.mark.asyncio
    async def test_agent_single_hop(self, mock_llm, mock_tools):
        """Test agent completes in single hop."""
        from unified_api.services.agentic_rag.agent import AgenticRagAgent

        # Mock LLM to select SQL tool then synthesize
        mock_llm.ainvoke.side_effect = [
            Mock(content=json.dumps({
                "thought": "I need to query the deals table",
                "tool": "sql",
                "query": "SELECT * FROM deals",
                "synthesize": False,
            })),
            Mock(content=json.dumps({
                "thought": "I have enough information to answer",
                "tool": "synthesize",
                "query": "Found 5 deals related to your query.",
                "synthesize": True,
            })),
            Mock(content="Found 2 deals related to your query."),
        ]

        mock_tools[ToolType.SQL].execute.return_value = ToolResult(
            success=True,
            data=[{"id": 1}, {"id": 2}],
            row_count=2
        )

        agent = AgenticRagAgent(llm=mock_llm, tools=mock_tools)
        result = await agent.run("Find deals")

        assert result.success is True
        assert result.answer == "Found 2 deals related to your query."
        assert len(result.reasoning_steps) == 1

    @pytest.mark.asyncio
    async def test_agent_max_hops_reached(self, mock_llm, mock_tools):
        """Test agent stops at max hops."""
        from unified_api.services.agentic_rag.agent import AgenticRagAgent

        # Always want to query more
        mock_llm.ainvoke.return_value = Mock(content=json.dumps({
            "thought": "Need more data",
            "tool": "sql",
            "query": "SELECT * FROM more_data",
            "synthesize": False,
        }))

        mock_tools[ToolType.SQL].execute.return_value = ToolResult(
            success=True, data=[], row_count=0
        )

        agent = AgenticRagAgent(
            llm=mock_llm,
            tools=mock_tools,
            max_hops=2
        )
        result = await agent.run("Complex query")

        assert result.success is True  # Returns partial
        assert result.partial is True
        assert len(result.reasoning_steps) == 1
        assert "inconclusive" in result.answer.lower()

    @pytest.mark.asyncio
    async def test_agent_tool_retry_then_skip(self, mock_llm, mock_tools):
        """Test agent retries failed tool then skips."""
        from unified_api.services.agentic_rag.agent import AgenticRagAgent

        mock_llm.ainvoke.side_effect = [
            Mock(content=json.dumps({"thought": "Query SQL", "tool": "sql", "query": "SELECT 1", "synthesize": False})),
            Mock(content="SELECT 2"),
            Mock(content="SELECT 3"),
            Mock(content=json.dumps({"thought": "Try Neo4j instead", "tool": "neo4j", "query": "MATCH (n) RETURN n", "synthesize": False})),
            Mock(content=json.dumps({"thought": "Synthesize from what we have", "tool": "synthesize", "query": "Partial answer", "synthesize": True})),
            Mock(content="Partial answer"),
        ]

        # SQL fails twice
        mock_tools[ToolType.SQL].execute.return_value = ToolResult(
            success=False, error="DB down", row_count=0
        )
        # Neo4j succeeds
        mock_tools[ToolType.NEO4J].execute.return_value = ToolResult(
            success=True, data=[{"n": 1}], row_count=1
        )

        agent = AgenticRagAgent(llm=mock_llm, tools=mock_tools, max_retries_per_tool=2)
        result = await agent.run("Test query")

        assert result.success is True
        assert len(result.reasoning_steps) == 2  # SQL (failed) + Neo4j (success) + synthesize

    @pytest.mark.asyncio
    async def test_synthesis_prompt_contains_tool_rows(self, mock_llm, mock_tools):
        from unified_api.services.agentic_rag.agent import AgenticRagAgent

        mock_llm.ainvoke.side_effect = [
            Mock(content=json.dumps({
                "thought": "Query SQL",
                "tool": "sql",
                "query": "SELECT id, title FROM deals LIMIT 1",
                "synthesize": False,
            })),
            Mock(content=json.dumps({
                "thought": "Synthesize",
                "tool": "synthesize",
                "query": None,
                "synthesize": True,
            })),
            Mock(content="Deal 42 is the matching record."),
        ]
        mock_tools[ToolType.SQL].execute.return_value = ToolResult(
            success=True,
            data=[{"id": 42, "title": "Evidence-backed deal"}],
            row_count=1,
            query_executed="SELECT id, title FROM deals LIMIT 1",
        )

        result = await AgenticRagAgent(llm=mock_llm, tools=mock_tools).run("Find it")

        assert result.answer == "Deal 42 is the matching record."
        synthesis_prompt = mock_llm.ainvoke.await_args_list[-1].args[0]
        assert "Evidence-backed deal" in synthesis_prompt

    def test_neo4j_schema_matches_graph_sync_direction_and_value(self):
        from unified_api.services.agentic_rag.tools.neo4j_tool import Neo4jTool

        schema = Neo4jTool.SCHEMA_DESCRIPTION

        assert "(Company)-[:LICENSES_OUT]->(Deal)" in schema
        assert "total_value (number or null)" in schema
        assert "never exact equality" in schema


class TestStreamingResponse:
    """Test streaming response generation."""

    @pytest.mark.asyncio
    async def test_streaming_events(self):
        """Test that streaming yields correct events."""
        from unified_api.services.agentic_rag.agent import AgenticRagAgent

        mock_llm = Mock()
        mock_llm.ainvoke = AsyncMock(side_effect=[
            Mock(content=json.dumps({"thought": "Step 1", "tool": "sql", "query": "SELECT 1", "synthesize": False})),
            Mock(content=json.dumps({"thought": "Step 2", "tool": "synthesize", "query": "Done", "synthesize": True})),
            Mock(content="Done"),
        ])

        sql_tool = Mock()
        sql_tool.is_available.return_value = True
        sql_tool.get_schema_description.return_value = "sql schema"
        sql_tool.execute = AsyncMock()
        mock_tools = {ToolType.SQL: sql_tool}
        mock_tools[ToolType.SQL].execute.return_value = ToolResult(
            success=True, data=[{}], row_count=1
        )

        agent = AgenticRagAgent(llm=mock_llm, tools=mock_tools)

        events = []
        async for event in agent.run_streaming("Test"):
            events.append(event)

        # Streaming currently emits initialization, completed reasoning steps, and answer.
        assert len(events) >= 3
        assert any(e.type == "thinking" for e in events)
        assert any(e.type == "answer" for e in events)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
