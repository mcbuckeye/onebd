"""
TDD: Contract comparison endpoint upgrade tests.

Tests for full-text contract comparison using PageIndex.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestDeepCompare:
    """Deep contract comparison using PageIndex."""

    @pytest.mark.asyncio
    async def test_deep_compare_returns_comparison(self):
        from unified_api.services.contract_compare import deep_compare_contracts

        mock_session_factory = MagicMock()

        import sys
        mock_litellm = MagicMock()
        mock_litellm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Comparison table here"))]
        )
        sys.modules["litellm"] = mock_litellm

        try:
            with patch("unified_api.services.agentic_rag.tools.pageindex_tool.PageIndexTool") as MockTool:
                mock_tool = AsyncMock()
                MockTool.return_value = mock_tool

                mock_tool._execute_impl.return_value = MagicMock(
                    success=True,
                    data=[{"answer": "Upfront: $6M, Royalties: 5%", "sections_consulted": 3}],
                )

                result = await deep_compare_contracts(
                    deal_ids=[100, 200],
                    comparison_aspects=["financial terms", "termination"],
                    session_factory=mock_session_factory,
                    openai_api_key="test-key",
                )

                assert result is not None
                assert "deals" in result
                assert "comparison" in result
        finally:
            del sys.modules["litellm"]

    @pytest.mark.asyncio
    async def test_deep_compare_handles_missing_contracts(self):
        from unified_api.services.contract_compare import deep_compare_contracts

        mock_session_factory = MagicMock()

        import sys
        mock_litellm = MagicMock()
        mock_litellm.completion.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content="Limited comparison"))]
        )
        sys.modules["litellm"] = mock_litellm

        try:
            with patch("unified_api.services.agentic_rag.tools.pageindex_tool.PageIndexTool") as MockTool:
                mock_tool = AsyncMock()
                MockTool.return_value = mock_tool

                mock_tool._execute_impl.return_value = MagicMock(
                    success=False,
                    error="No contract found",
                    data=None,
                )

                result = await deep_compare_contracts(
                    deal_ids=[100],
                    comparison_aspects=["financial terms"],
                    session_factory=mock_session_factory,
                    openai_api_key="test-key",
                )

                assert result is not None
        finally:
            del sys.modules["litellm"]


class TestComparisonAspects:
    """Identifying what to compare."""

    def test_default_aspects(self):
        import sys
        sys.modules["litellm"] = MagicMock()
        from unified_api.services.contract_compare import DEFAULT_COMPARISON_ASPECTS
        assert "financial terms" in DEFAULT_COMPARISON_ASPECTS
        assert "termination" in DEFAULT_COMPARISON_ASPECTS
        assert "ip ownership" in DEFAULT_COMPARISON_ASPECTS
