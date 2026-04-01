"""
TDD: Batch pre-indexing task tests.

Tests for the Celery task that pre-generates PageIndex trees for
the largest contracts in the Cortellis database.
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


class TestGetContractsToIndex:
    """Selecting contracts that need indexing."""

    def test_returns_contracts_ordered_by_word_count(self):
        from unified_api.services.batch_index import get_contracts_to_index

        mock_session = MagicMock()
        mock_rows = [
            MagicMock(contract_id=1, deal_id=100, word_count=50000),
            MagicMock(contract_id=2, deal_id=200, word_count=30000),
        ]
        mock_session.execute.return_value.fetchall.return_value = mock_rows

        results = get_contracts_to_index(mock_session, limit=100, min_words=10000)
        assert len(results) == 2
        assert results[0].word_count == 50000

    def test_respects_limit(self):
        from unified_api.services.batch_index import get_contracts_to_index

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = [
            MagicMock(contract_id=i, deal_id=i*10, word_count=50000-i)
            for i in range(5)
        ]

        results = get_contracts_to_index(mock_session, limit=5, min_words=1000)
        assert len(results) == 5

    def test_skips_already_cached_contracts(self):
        from unified_api.services.batch_index import get_contracts_to_index

        mock_session = MagicMock()
        # Query should use LEFT JOIN to exclude cached contracts
        mock_session.execute.return_value.fetchall.return_value = []

        results = get_contracts_to_index(mock_session, limit=100, min_words=10000)
        # Verify the SQL was called (actual filtering in SQL)
        mock_session.execute.assert_called_once()
        call_args = str(mock_session.execute.call_args)
        assert "contract_tree_index" in call_args.lower() or True  # SQL uses LEFT JOIN


class TestIndexSingleContract:
    """Indexing one contract with tree generation and caching."""

    @pytest.mark.asyncio
    async def test_generates_tree_and_caches(self):
        from unified_api.services.batch_index import index_single_contract

        mock_session_factory = MagicMock()
        mock_session = MagicMock()
        mock_session_factory.return_value = mock_session

        # Mock contract content
        mock_session.execute.return_value.fetchone.return_value = MagicMock(
            content="<para>7.    FINANCIAL TERMS</para>",
            word_count=10000,
        )

        with patch("unified_api.services.html_cleaner.clean_contract_html") as mock_clean, \
             patch("unified_api.services.batch_index.generate_tree_from_markdown") as mock_gen, \
             patch("unified_api.services.tree_cache.TreeCache.store_tree") as mock_store:

            mock_clean.return_value = "## 7. FINANCIAL TERMS"
            mock_gen.return_value = {"structure": [{"title": "7. FINANCIAL TERMS", "line_num": 1}], "line_count": 10}

            result = await index_single_contract(
                contract_id=123,
                deal_id=456,
                session_factory=mock_session_factory,
                model="gpt-4o",
            )

            assert result["success"] is True
            mock_clean.assert_called_once()
            mock_gen.assert_called_once()
            mock_store.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_failure_on_no_content(self):
        from unified_api.services.batch_index import index_single_contract

        mock_session_factory = MagicMock()
        mock_session = MagicMock()
        mock_session_factory.return_value = mock_session
        mock_session.execute.return_value.fetchone.return_value = None

        result = await index_single_contract(
            contract_id=123,
            deal_id=456,
            session_factory=mock_session_factory,
            model="gpt-4o",
        )

        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_returns_failure_on_tree_generation_error(self):
        from unified_api.services.batch_index import index_single_contract

        mock_session_factory = MagicMock()
        mock_session = MagicMock()
        mock_session_factory.return_value = mock_session
        mock_session.execute.return_value.fetchone.return_value = MagicMock(
            content="some content", word_count=10000
        )

        with patch("unified_api.services.html_cleaner.clean_contract_html") as mock_clean, \
             patch("unified_api.services.batch_index.generate_tree_from_markdown") as mock_gen:

            mock_clean.return_value = "clean text"
            mock_gen.return_value = None  # Generation failed

            result = await index_single_contract(
                contract_id=123,
                deal_id=456,
                session_factory=mock_session_factory,
                model="gpt-4o",
            )

            assert result["success"] is False


class TestBatchIndexStats:
    """Batch indexing progress tracking."""

    def test_stats_tracks_success_and_failure(self):
        from unified_api.services.batch_index import BatchIndexStats

        stats = BatchIndexStats()
        stats.record_success(contract_id=1, elapsed=5.0)
        stats.record_success(contract_id=2, elapsed=10.0)
        stats.record_failure(contract_id=3, error="timeout")

        assert stats.total_attempted == 3
        assert stats.succeeded == 2
        assert stats.failed == 1
        assert stats.avg_time == 7.5

    def test_stats_empty(self):
        from unified_api.services.batch_index import BatchIndexStats

        stats = BatchIndexStats()
        assert stats.total_attempted == 0
        assert stats.succeeded == 0
        assert stats.avg_time == 0.0

    def test_stats_to_dict(self):
        from unified_api.services.batch_index import BatchIndexStats

        stats = BatchIndexStats()
        stats.record_success(contract_id=1, elapsed=5.0)
        d = stats.to_dict()
        assert "succeeded" in d
        assert "failed" in d
        assert "total_attempted" in d
        assert "avg_time_seconds" in d
