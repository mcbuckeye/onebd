"""
TDD: PDF support tests for PageIndex tool.

Tests for indexing original SEC/EDGAR PDF filings directly
instead of just the HTML text in contract_content.
"""
import pytest
from unittest.mock import MagicMock, patch


class TestPdfTreeGeneration:
    """PDF tree generation via PageIndex."""

    @pytest.mark.asyncio
    async def test_generate_pdf_tree(self):
        import sys
        mock_page_index_mod = MagicMock()
        mock_page_index_mod.page_index.return_value = {
            "structure": [{"title": "Section 1", "start_index": 1, "end_index": 5}],
            "doc_name": "test.pdf",
        }
        sys.modules["unified_api.vendor.pageindex.page_index"] = mock_page_index_mod

        try:
            # Force reimport
            if "unified_api.services.pdf_indexer" in sys.modules:
                del sys.modules["unified_api.services.pdf_indexer"]
            from unified_api.services.pdf_indexer import generate_pdf_tree

            result = await generate_pdf_tree("/path/to/test.pdf", model="gpt-4o")
            assert result is not None
            assert "structure" in result
        finally:
            del sys.modules["unified_api.vendor.pageindex.page_index"]

    @pytest.mark.asyncio
    async def test_generate_pdf_tree_returns_none_on_error(self):
        import sys
        mock_page_index_mod = MagicMock()
        mock_page_index_mod.page_index.side_effect = Exception("PDF parsing failed")
        sys.modules["unified_api.vendor.pageindex.page_index"] = mock_page_index_mod

        try:
            if "unified_api.services.pdf_indexer" in sys.modules:
                del sys.modules["unified_api.services.pdf_indexer"]
            from unified_api.services.pdf_indexer import generate_pdf_tree

            result = await generate_pdf_tree("/path/to/bad.pdf", model="gpt-4o")
            assert result is None
        finally:
            del sys.modules["unified_api.vendor.pageindex.page_index"]


class TestPreferPdfTree:
    """PDF tree preferred over markdown tree when available."""

    def test_prefer_pdf_checks_pdf_path(self):
        from unified_api.services.pdf_indexer import has_pdf_for_contract

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = MagicMock(
            pdf_file_path="/data/contracts/deal_150059.pdf",
            has_pdf=True,
        )

        result = has_pdf_for_contract(mock_session, contract_id=123)
        assert result is not None
        assert result["has_pdf"] is True

    def test_no_pdf_returns_none(self):
        from unified_api.services.pdf_indexer import has_pdf_for_contract

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = MagicMock(
            pdf_file_path=None,
            has_pdf=False,
        )

        result = has_pdf_for_contract(mock_session, contract_id=123)
        assert result["has_pdf"] is False
