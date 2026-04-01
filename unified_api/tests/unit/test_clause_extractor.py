"""
TDD: Clause extractor tests — tree-guided and brute-force extraction.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


class TestFindRelevantLinesFromTree:
    """Tree section keyword matching."""

    def test_finds_financial_sections(self):
        from unified_api.services.clause_extractor import _find_relevant_lines_from_tree
        tree = {
            "structure": [
                {"title": "1. DEFINITIONS", "line_num": 100},
                {"title": "7. FINANCIAL TERMS", "line_num": 500, "nodes": [
                    {"title": "7.1 Upfront Payment", "line_num": 501},
                    {"title": "7.9 Royalties", "line_num": 550},
                ]},
                {"title": "11. TERMINATION", "line_num": 800},
            ]
        }
        lines = _find_relevant_lines_from_tree(tree)
        assert 500 in lines  # financial
        assert 501 in lines  # payment
        assert 550 in lines  # royalty
        assert 800 in lines  # termination
        assert 100 not in lines  # definitions — not a clause section

    def test_finds_ip_and_license_sections(self):
        from unified_api.services.clause_extractor import _find_relevant_lines_from_tree
        tree = {
            "structure": [
                {"title": "3. LICENSE GRANTS", "line_num": 200},
                {"title": "6. INTELLECTUAL PROPERTY", "line_num": 400},
                {"title": "9. CONFIDENTIALITY", "line_num": 600},
            ]
        }
        lines = _find_relevant_lines_from_tree(tree)
        assert 200 in lines
        assert 400 in lines
        assert 600 in lines

    def test_empty_tree_returns_empty(self):
        from unified_api.services.clause_extractor import _find_relevant_lines_from_tree
        assert _find_relevant_lines_from_tree({"structure": []}) == []
        assert _find_relevant_lines_from_tree({}) == []

    def test_skips_zero_line_numbers(self):
        from unified_api.services.clause_extractor import _find_relevant_lines_from_tree
        tree = {"structure": [{"title": "7. FINANCIAL TERMS", "line_num": 0}]}
        assert _find_relevant_lines_from_tree(tree) == []

    def test_deduplicates_and_sorts(self):
        from unified_api.services.clause_extractor import _find_relevant_lines_from_tree
        tree = {
            "structure": [
                {"title": "Payment Terms", "line_num": 300},
                {"title": "Milestone Payments", "line_num": 300},  # duplicate
                {"title": "Royalty Schedule", "line_num": 100},
            ]
        }
        lines = _find_relevant_lines_from_tree(tree)
        assert lines == sorted(set(lines))


class TestExtractClausesRouting:
    """extract_clauses tries tree-guided first, falls back to brute-force."""

    @pytest.mark.asyncio
    @patch("unified_api.services.clause_extractor._extract_brute_force")
    async def test_no_deal_id_uses_brute_force(self, mock_brute):
        from unified_api.services.clause_extractor import extract_clauses
        mock_brute.return_value = {"upfront_payment": None}
        with patch("unified_api.services.clause_extractor.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_model = "gpt-4o"
            result = await extract_clauses("contract text here", deal_id=None)
        mock_brute.assert_called_once()

    @pytest.mark.asyncio
    @patch("unified_api.services.clause_extractor.extract_clauses_with_tree")
    async def test_deal_id_with_cached_tree_uses_tree_guided(self, mock_tree_extract):
        from unified_api.services.clause_extractor import extract_clauses
        mock_tree_extract.return_value = {"upfront_payment": {"amount": 6}}

        # Mock the imports that happen inside extract_clauses
        mock_cache = MagicMock()
        mock_cache.get_tree_by_deal.return_value = {"structure": []}

        with (
            patch("unified_api.services.clause_extractor.settings") as mock_settings,
            patch("unified_api.services.tree_cache.TreeCache", return_value=mock_cache),
            patch("unified_api.services.database.get_cortellis_session_factory", return_value=MagicMock()),
        ):
            mock_settings.openai_api_key = "test-key"
            result = await extract_clauses("contract text", deal_id=12345)

        mock_tree_extract.assert_called_once()

    @pytest.mark.asyncio
    @patch("unified_api.services.clause_extractor._extract_brute_force")
    async def test_tree_failure_falls_back_to_brute_force(self, mock_brute):
        from unified_api.services.clause_extractor import extract_clauses
        mock_brute.return_value = {"upfront_payment": None}

        with (
            patch("unified_api.services.clause_extractor.settings") as mock_settings,
            patch("unified_api.services.tree_cache.TreeCache", side_effect=Exception("DB error")),
            patch("unified_api.services.database.get_cortellis_session_factory", return_value=MagicMock()),
        ):
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_model = "gpt-4o"
            result = await extract_clauses("contract text", deal_id=12345)

        mock_brute.assert_called_once()


class TestClauseExtractionMetadata:
    """Extraction results include method metadata."""

    @pytest.mark.asyncio
    @patch("unified_api.services.clause_extractor._extract_brute_force")
    async def test_brute_force_metadata(self, mock_brute):
        from unified_api.services.clause_extractor import extract_clauses
        mock_brute.return_value = {
            "upfront_payment": None,
            "_metadata": {"extraction_method": "brute_force"},
        }
        with patch("unified_api.services.clause_extractor.settings") as mock_settings:
            mock_settings.openai_api_key = "test-key"
            mock_settings.openai_model = "gpt-4o"
            result = await extract_clauses("text")
        assert result["_metadata"]["extraction_method"] == "brute_force"
