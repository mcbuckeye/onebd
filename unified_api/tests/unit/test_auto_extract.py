"""
TDD: Auto-extract clause data tests.

Tests for automatic clause extraction when trees are generated,
storing structured deal terms in a queryable JSONB column.
"""
import pytest
from unittest.mock import MagicMock, patch


class TestAutoExtractClauses:
    """Auto-extraction triggered after tree generation."""

    @pytest.mark.asyncio
    async def test_extracts_and_stores_clauses(self):
        from unified_api.services.auto_extract import auto_extract_clauses

        mock_session_factory = MagicMock()
        mock_session = MagicMock()
        mock_session_factory.return_value = mock_session

        # Mock: contract has content and a cached tree
        mock_session.execute.return_value.fetchone.return_value = MagicMock(
            content="<para>7.1 Upfront Payment. $6M</para>",
        )

        tree_json = {"structure": [
            {"title": "7. FINANCIAL TERMS", "line_num": 100},
            {"title": "7.1 Upfront Payment", "line_num": 101},
        ]}

        with patch("unified_api.services.clause_extractor.extract_clauses_with_tree") as mock_extract:
            mock_extract.return_value = {
                "upfront_payment": {"amount": 6, "currency": "USD"},
                "royalty_rates": None,
            }

            result = await auto_extract_clauses(
                contract_id=123,
                deal_id=456,
                tree_json=tree_json,
                session_factory=mock_session_factory,
            )

            assert result["success"] is True
            mock_extract.assert_called_once()
            # Should have stored the extracted data
            assert mock_session.commit.called

    @pytest.mark.asyncio
    async def test_skips_if_no_content(self):
        from unified_api.services.auto_extract import auto_extract_clauses

        mock_session_factory = MagicMock()
        mock_session = MagicMock()
        mock_session_factory.return_value = mock_session
        mock_session.execute.return_value.fetchone.return_value = None

        result = await auto_extract_clauses(
            contract_id=123,
            deal_id=456,
            tree_json={"structure": []},
            session_factory=mock_session_factory,
        )

        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_handles_extraction_failure(self):
        from unified_api.services.auto_extract import auto_extract_clauses

        mock_session_factory = MagicMock()
        mock_session = MagicMock()
        mock_session_factory.return_value = mock_session
        mock_session.execute.return_value.fetchone.return_value = MagicMock(
            content="some contract text",
        )

        with patch("unified_api.services.clause_extractor.extract_clauses_with_tree") as mock_extract:
            mock_extract.side_effect = Exception("LLM timeout")

            result = await auto_extract_clauses(
                contract_id=123,
                deal_id=456,
                tree_json={"structure": []},
                session_factory=mock_session_factory,
            )

            assert result["success"] is False
            assert "timeout" in result["error"].lower()


class TestGetExtractedClauses:
    """Reading cached extracted clauses."""

    def test_returns_clauses_when_present(self):
        from unified_api.services.auto_extract import get_extracted_clauses

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = MagicMock(
            extracted_clauses={"upfront_payment": {"amount": 6, "currency": "USD"}},
        )

        result = get_extracted_clauses(mock_session, contract_id=123)
        assert result is not None
        assert result["upfront_payment"]["amount"] == 6

    def test_returns_none_when_absent(self):
        from unified_api.services.auto_extract import get_extracted_clauses

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = MagicMock(
            extracted_clauses=None,
        )

        result = get_extracted_clauses(mock_session, contract_id=123)
        assert result is None

    def test_returns_none_when_no_row(self):
        from unified_api.services.auto_extract import get_extracted_clauses

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchone.return_value = None

        result = get_extracted_clauses(mock_session, contract_id=123)
        assert result is None
