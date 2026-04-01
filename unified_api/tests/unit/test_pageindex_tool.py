"""
TDD: PageIndex agentic RAG tool tests.

Tests for PageIndexTool — deep contract reading with tree-based reasoning.
Uses mocks for DB, LLM, and PageIndex to test tool logic in isolation.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import json


class TestPageIndexToolInit:
    """Tool initialization and metadata."""

    def test_tool_name_is_pageindex(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(
            session_factory=MagicMock(),
            openai_api_key="test-key",
        )
        assert tool.name == "pageindex"

    def test_schema_description_mentions_contracts(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(
            session_factory=MagicMock(),
            openai_api_key="test-key",
        )
        desc = tool.get_schema_description()
        assert "contract" in desc.lower()
        assert "deal_id" in desc.lower()

    def test_schema_description_mentions_use_cases(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(
            session_factory=MagicMock(),
            openai_api_key="test-key",
        )
        desc = tool.get_schema_description()
        assert "royalty" in desc.lower()
        assert "milestone" in desc.lower()
        assert "termination" in desc.lower()


class TestQueryParsing:
    """Parsing deal_id and question from query string."""

    def test_parse_deal_id_from_query(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(session_factory=MagicMock(), openai_api_key="k")
        assert tool._parse_deal_id("deal_id:12345 What milestones?") == 12345

    def test_parse_deal_id_missing(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(session_factory=MagicMock(), openai_api_key="k")
        assert tool._parse_deal_id("What are the royalty rates?") is None

    def test_parse_deal_id_large_number(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(session_factory=MagicMock(), openai_api_key="k")
        assert tool._parse_deal_id("deal_id:150059 Tell me about IP") == 150059

    def test_get_question_strips_deal_id(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(session_factory=MagicMock(), openai_api_key="k")
        assert tool._get_question("deal_id:123 What are the royalties?") == "What are the royalties?"

    def test_get_question_without_deal_id(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(session_factory=MagicMock(), openai_api_key="k")
        assert tool._get_question("What are the royalties?") == "What are the royalties?"


class TestExecuteErrors:
    """Error handling in _execute_impl."""

    @pytest.mark.asyncio
    async def test_no_deal_id_returns_error(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(session_factory=MagicMock(), openai_api_key="k")
        result = await tool._execute_impl("What are the royalty rates?")
        assert not result.success
        assert "deal_id" in result.error.lower()

    @pytest.mark.asyncio
    async def test_no_contract_found_returns_error(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None
        tool = PageIndexTool(
            session_factory=lambda: mock_session,
            openai_api_key="k",
        )
        result = await tool._execute_impl("deal_id:99999 What are the terms?")
        assert not result.success
        assert "no contract" in result.error.lower()

    @pytest.mark.asyncio
    async def test_deal_id_from_kwargs(self):
        """deal_id can be passed via kwargs instead of query string."""
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None
        tool = PageIndexTool(
            session_factory=lambda: mock_session,
            openai_api_key="k",
        )
        result = await tool._execute_impl("What are the terms?", deal_id=12345)
        assert not result.success
        # Should have tried to look up deal 12345, not fail on missing deal_id
        assert "no contract" in result.error.lower()


class TestBuildCompactTree:
    """Tree index compression for LLM context."""

    def test_builds_compact_tree_text(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(session_factory=MagicMock(), openai_api_key="k")
        tree_data = {
            "structure": [
                {
                    "title": "1. DEFINITIONS",
                    "line_num": 100,
                    "nodes": [
                        {"title": "1.1 Affiliate", "line_num": 101},
                        {"title": "1.2 Term", "line_num": 102},
                    ],
                },
                {
                    "title": "7. FINANCIAL TERMS",
                    "line_num": 500,
                    "nodes": [
                        {"title": "7.1 Upfront Payment", "line_num": 501},
                    ],
                },
            ]
        }
        result = tool._build_compact_tree(tree_data)
        assert "[L100]" in result
        assert "[L500]" in result
        assert "FINANCIAL TERMS" in result
        assert "Upfront Payment" in result


class TestToolTypeEnum:
    """PAGEINDEX must be in ToolType enum."""

    def test_pageindex_in_tooltype(self):
        from unified_api.services.agentic_rag.models import ToolType
        assert hasattr(ToolType, "PAGEINDEX")
        assert ToolType.PAGEINDEX.value == "pageindex"
