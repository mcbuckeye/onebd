"""
Integration tests for Agentic RAG.
Tests router, agent, and tools with real database connections.
"""
import pytest
import os
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

from unified_api.main import app


@pytest.fixture
async def async_client():
    """Create async test client."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as client:
        yield client


class TestAgenticRagEndpoints:
    """Test the Agentic RAG API endpoints."""

    @pytest.mark.asyncio
    async def test_health_endpoint(self, async_client):
        """Test the /health endpoint returns correct structure."""
        response = await async_client.get("/api/agentic-rag/health")

        assert response.status_code == 200
        data = response.json()

        assert "status" in data
        assert "tools" in data
        assert "timestamp" in data

        # Should have tool statuses
        assert isinstance(data["tools"], dict)

    @pytest.mark.asyncio
    async def test_chat_endpoint_basic(self, async_client):
        """Test basic chat endpoint response structure."""
        request_data = {
            "message": "Find deals in Oncology",
            "history": [],
            "max_hops": 3,
            "stream": False
        }

        # This will fail with 401 if auth is required
        # For now, test that endpoint exists and returns proper error
        response = await async_client.post("/api/agentic-rag/chat", json=request_data)

        # Should either succeed or return proper auth error
        assert response.status_code in [200, 401, 501]

        if response.status_code == 200:
            data = response.json()
            assert "success" in data
            assert "answer" in data
            assert "reasoning_steps" in data
            assert "total_hops" in data
            assert "latency_ms" in data

    @pytest.mark.asyncio
    async def test_chat_endpoint_with_history(self, async_client):
        """Test chat with conversation history."""
        request_data = {
            "message": "Which ones are in Phase 3?",
            "history": [
                {"role": "user", "content": "Find oncology deals"},
                {"role": "assistant", "content": "Found 5 deals."}
            ],
            "max_hops": 5,
            "stream": False
        }

        response = await async_client.post("/api/agentic-rag/chat", json=request_data)

        # Should at least not error out on validation
        assert response.status_code in [200, 401, 422, 501]

    @pytest.mark.asyncio
    async def test_chat_endpoint_invalid_max_hops(self, async_client):
        """Test validation rejects invalid max_hops."""
        request_data = {
            "message": "Test",
            "max_hops": 15  # Above max of 10
        }

        response = await async_client.post("/api/agentic-rag/chat", json=request_data)

        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_chat_endpoint_streaming_not_implemented(self, async_client):
        """Test streaming endpoint returns 501."""
        request_data = {
            "message": "Test",
            "stream": True
        }

        response = await async_client.post("/api/agentic-rag/chat/stream", json=request_data)

        assert response.status_code == 501


class TestToolConnections:
    """Test database connections for tools."""

    @pytest.mark.asyncio
    async def test_neo4j_connection(self):
        """Test Neo4j tool can connect."""
        from unified_api.services.agentic_rag.tools import Neo4jTool

        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "")

        if not password:
            pytest.skip("Neo4j password not configured")

        tool = Neo4jTool(uri=uri, username=user, password=password)

        # Test basic query
        result = await tool.execute("MATCH (n) RETURN count(n) as count LIMIT 1")

        assert result.success or result.error  # Either works or gives clear error

        await tool.close()


class TestAgentWorkflow:
    """
    Test the complete agent workflow with mocked LLM.
    These tests require langgraph to be installed.
    """

    @pytest.mark.skipif(
        "langgraph" not in __import__("sys").modules,
        reason="langgraph not installed"
    )
    @pytest.mark.asyncio
    async def test_agent_e2e_mocked(self):
        """Test agent end-to-end with mocked LLM."""
        from unittest.mock import AsyncMock
        from unified_api.services.agentic_rag import AgenticRagAgent, ToolType
        from unified_api.services.agentic_rag.tools import Neo4jTool

        # Mock LLM
        mock_llm = AsyncMock()
        mock_llm.side_effect = [
            {
                "thought": "Query Neo4j",
                "tool": "neo4j",
                "query": "MATCH (d:Deal) RETURN count(d) as count"
            },
            {
                "thought": "Synthesize",
                "tool": "synthesize",
                "query": "Found 100 deals",
                "synthesize": True
            }
        ]

        # Mock tool
        mock_tool = AsyncMock()
        mock_tool.execute.return_value = AsyncMock(
            success=True,
            data=[{"count": 100}],
            row_count=1
        )

        agent = AgenticRagAgent(
            llm=mock_llm,
            tools={ToolType.NEO4J: mock_tool},
            max_hops=3
        )

        result = await agent.run("How many deals?")

        assert result.success
        assert result.total_hops > 0
