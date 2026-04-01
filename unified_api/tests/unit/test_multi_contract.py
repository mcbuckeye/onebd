"""
TDD: Multi-contract query tests.

Tests for querying and comparing across multiple contracts simultaneously.
"""
import pytest
from unittest.mock import MagicMock, patch


class TestParseDealIds:
    """Parsing multiple deal IDs from query strings."""

    def test_parse_comma_separated(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(session_factory=MagicMock(), openai_api_key="k")
        ids = tool._parse_deal_ids("deal_ids:150059,107441,112856 Compare milestones")
        assert ids == [150059, 107441, 112856]

    def test_parse_single_deal_id_still_works(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(session_factory=MagicMock(), openai_api_key="k")
        ids = tool._parse_deal_ids("deal_id:150059 What are the royalties?")
        assert ids == [150059]

    def test_parse_no_deal_ids(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(session_factory=MagicMock(), openai_api_key="k")
        ids = tool._parse_deal_ids("What are the royalties?")
        assert ids == []

    def test_parse_limits_to_five(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(session_factory=MagicMock(), openai_api_key="k")
        ids = tool._parse_deal_ids("deal_ids:1,2,3,4,5,6,7,8 Compare")
        assert len(ids) == 5

    def test_parse_deal_ids_from_kwargs(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(session_factory=MagicMock(), openai_api_key="k")
        # deal_ids kwarg should also work
        ids = tool._parse_deal_ids("Compare milestones", deal_ids=[100, 200, 300])
        assert ids == [100, 200, 300]


class TestGetQuestionMulti:
    """Extracting question from multi-deal query."""

    def test_strips_deal_ids(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(session_factory=MagicMock(), openai_api_key="k")
        q = tool._get_question("deal_ids:150059,107441 Compare milestone structures")
        assert q == "Compare milestone structures"

    def test_strips_single_deal_id(self):
        from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool
        tool = PageIndexTool(session_factory=MagicMock(), openai_api_key="k")
        q = tool._get_question("deal_id:150059 What are the royalties?")
        assert q == "What are the royalties?"
