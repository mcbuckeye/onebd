"""
Search Integration Tests for BD Intelligence Platform

Tests search functionality across:
- Cortellis contract search (fulltext + semantic)
- Edgar SEC filing search (fulltext + semantic)
- Unified cross-source search
- Deal search with filters
"""
import pytest
from sqlalchemy import text
from typing import List, Dict, Any


@pytest.mark.integration
@pytest.mark.cortellis
class TestCortellisContractSearch:
    """Tests for Cortellis contract search functionality."""

    def test_fulltext_search_returns_results(self, cortellis_session):
        """Verify fulltext search returns relevant results."""
        # Common contract term that should return results
        query = "royalty"

        result = cortellis_session.execute(text("""
            SELECT
                cc.id,
                cc.deal_id,
                cc.content,
                ts_rank(to_tsvector('english', cc.content),
                        plainto_tsquery('english', :query)) as score
            FROM contract_chunks cc
            WHERE to_tsvector('english', cc.content) @@
                  plainto_tsquery('english', :query)
            ORDER BY score DESC
            LIMIT 10
        """), {"query": query})

        results = result.fetchall()
        assert len(results) > 0, f"No results found for query '{query}'"

        # Results should contain the search term
        for row in results:
            assert query.lower() in row.content.lower() or \
                   "royalt" in row.content.lower(), \
                   "Result doesn't contain search term"

    def test_fulltext_search_ranking(self, cortellis_session):
        """Verify search results are properly ranked."""
        query = "license agreement"

        result = cortellis_session.execute(text("""
            SELECT
                ts_rank(to_tsvector('english', cc.content),
                        plainto_tsquery('english', :query)) as score
            FROM contract_chunks cc
            WHERE to_tsvector('english', cc.content) @@
                  plainto_tsquery('english', :query)
            ORDER BY score DESC
            LIMIT 20
        """), {"query": query})

        scores = [row.score for row in result]
        assert len(scores) > 0, "No results to check ranking"

        # Verify descending order
        for i in range(1, len(scores)):
            assert scores[i] <= scores[i-1], "Results not properly ranked"

    def test_semantic_search_embeddings_exist(self, cortellis_session):
        """Verify embeddings are available for semantic search."""
        result = cortellis_session.execute(text("""
            SELECT COUNT(*) FROM contract_chunks
            WHERE embedding IS NOT NULL
        """))
        count = result.scalar()
        assert count > 0, "No contract chunks have embeddings for semantic search"

    @pytest.mark.slow
    def test_semantic_search_vector_similarity(self, cortellis_session):
        """Test vector similarity search (requires embeddings)."""
        # Get a sample embedding to use as query
        result = cortellis_session.execute(text("""
            SELECT embedding, id
            FROM contract_chunks
            WHERE embedding IS NOT NULL
            LIMIT 1
        """))
        row = result.fetchone()

        if not row or not row.embedding:
            pytest.skip("No embeddings available for semantic search test")

        # Search for similar chunks
        result = cortellis_session.execute(text("""
            SELECT
                id,
                1 - (embedding <=> :query_embedding) as similarity
            FROM contract_chunks
            WHERE embedding IS NOT NULL
              AND id != :exclude_id
            ORDER BY embedding <=> :query_embedding
            LIMIT 5
        """), {
            "query_embedding": str(row.embedding),
            "exclude_id": row.id
        })

        similar = result.fetchall()
        assert len(similar) > 0, "Semantic search returned no similar chunks"

        # Similarity should be between 0 and 1
        for row in similar:
            assert 0 <= row.similarity <= 1, \
                f"Invalid similarity score: {row.similarity}"


@pytest.mark.integration
@pytest.mark.edgar
class TestEdgarFilingSearch:
    """Tests for Edgar SEC filing search functionality."""

    def test_fulltext_search_returns_results(self, edgar_source_session):
        """Verify fulltext search returns results from SEC filings."""
        # Common SEC filing term
        query = "material contract"

        result = edgar_source_session.execute(text("""
            SELECT
                c.id,
                c.document_id,
                c.text,
                ts_rank(to_tsvector('english', c.text),
                        plainto_tsquery('english', :query)) as score
            FROM chunks c
            WHERE to_tsvector('english', c.text) @@
                  plainto_tsquery('english', :query)
            ORDER BY score DESC
            LIMIT 10
        """), {"query": query})

        results = result.fetchall()
        assert len(results) > 0, f"No results found for query '{query}'"

    def test_search_with_filing_type_filter(self, edgar_source_session):
        """Verify search can filter by filing type."""
        query = "agreement"

        result = edgar_source_session.execute(text("""
            SELECT c.id, d.doc_type
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE to_tsvector('english', c.text) @@
                  plainto_tsquery('english', :query)
              AND d.doc_type = '8-K'
            LIMIT 5
        """), {"query": query})

        results = result.fetchall()
        # Should find some 8-K results
        for row in results:
            assert row.doc_type == '8-K', "Filter not properly applied"

    def test_search_returns_company_info(self, edgar_source_session):
        """Verify search results include company information."""
        query = "acquisition"

        result = edgar_source_session.execute(text("""
            SELECT
                c.id as chunk_id,
                e.name as company_name,
                e.ticker
            FROM chunks c
            JOIN documents d ON c.document_id = d.id
            JOIN raw_documents r ON d.raw_document_id = r.id
            JOIN companies e ON r.company_id = e.id
            WHERE to_tsvector('english', c.text) @@
                  plainto_tsquery('english', :query)
            LIMIT 5
        """), {"query": query})

        results = result.fetchall()
        for row in results:
            assert row.company_name is not None, "Missing company name"


@pytest.mark.integration
@pytest.mark.cortellis
@pytest.mark.edgar
class TestUnifiedSearch:
    """Tests for unified cross-source search."""

    def test_unified_search_both_sources(
        self, cortellis_session, edgar_source_session
    ):
        """Verify unified search queries both sources."""
        query = "license"

        # Search Cortellis
        cortellis_result = cortellis_session.execute(text("""
            SELECT COUNT(*)
            FROM contract_chunks cc
            WHERE to_tsvector('english', cc.content) @@
                  plainto_tsquery('english', :query)
        """), {"query": query})
        cortellis_count = cortellis_result.scalar()

        # Search Edgar
        edgar_result = edgar_source_session.execute(text("""
            SELECT COUNT(*)
            FROM chunks c
            WHERE to_tsvector('english', c.text) @@
                  plainto_tsquery('english', :query)
        """), {"query": query})
        edgar_count = edgar_result.scalar()

        # Both should return results
        assert cortellis_count > 0, "No Cortellis results for unified search"
        assert edgar_count > 0, "No Edgar results for unified search"

    def test_search_result_normalization(
        self, cortellis_session, edgar_source_session
    ):
        """Verify search results can be normalized across sources."""
        query = "partnership"

        # Get sample results from both
        cortellis_result = cortellis_session.execute(text("""
            SELECT
                cc.id as chunk_id,
                cc.deal_id,
                cc.content,
                ts_rank(to_tsvector('english', cc.content),
                        plainto_tsquery('english', :query)) as score
            FROM contract_chunks cc
            WHERE to_tsvector('english', cc.content) @@
                  plainto_tsquery('english', :query)
            LIMIT 3
        """), {"query": query})

        edgar_result = edgar_source_session.execute(text("""
            SELECT
                c.id as chunk_id,
                c.document_id,
                c.text as content,
                ts_rank(to_tsvector('english', c.text),
                        plainto_tsquery('english', :query)) as score
            FROM chunks c
            WHERE to_tsvector('english', c.text) @@
                  plainto_tsquery('english', :query)
            LIMIT 3
        """), {"query": query})

        cortellis_rows = cortellis_result.fetchall()
        edgar_rows = edgar_result.fetchall()

        # Both should return comparable fields
        for row in cortellis_rows:
            assert hasattr(row, 'chunk_id')
            assert hasattr(row, 'content')
            assert hasattr(row, 'score')

        for row in edgar_rows:
            assert hasattr(row, 'chunk_id')
            assert hasattr(row, 'content')
            assert hasattr(row, 'score')


@pytest.mark.integration
@pytest.mark.cortellis
class TestDealSearch:
    """Tests for deal search with filtering."""

    def test_search_by_deal_type(self, cortellis_session):
        """Verify search can filter by agreement type."""
        # Note: deals.deal_type is empty; use agreement_type instead
        result = cortellis_session.execute(text("""
            SELECT id, title, agreement_type
            FROM deals
            WHERE agreement_type ILIKE '%license%'
            LIMIT 10
        """))

        results = result.fetchall()
        assert len(results) > 0, "No license deals found"
        for row in results:
            assert 'license' in row.agreement_type.lower(), \
                f"Unexpected agreement type: {row.agreement_type}"

    def test_search_by_date_range(self, cortellis_session):
        """Verify search can filter by date range."""
        result = cortellis_session.execute(text("""
            SELECT id, title, date_start
            FROM deals
            WHERE date_start >= '2023-01-01'
              AND date_start < '2024-01-01'
            LIMIT 10
        """))

        results = result.fetchall()
        assert len(results) > 0, "No deals found in date range"
        for row in results:
            assert row.date_start.year == 2023, \
                f"Deal outside date range: {row.date_start}"

    def test_search_by_company(self, cortellis_session):
        """Verify search can filter by company name."""
        result = cortellis_session.execute(text("""
            SELECT d.id, d.title, c.name as company_name
            FROM deals d
            JOIN deal_companies dc ON dc.deal_id = d.id
            JOIN companies c ON c.id = dc.company_id
            WHERE c.name ILIKE '%pfizer%'
            LIMIT 10
        """))

        results = result.fetchall()
        assert len(results) > 0, "No Pfizer deals found"
        for row in results:
            assert 'pfizer' in row.company_name.lower(), \
                f"Unexpected company: {row.company_name}"

    def test_search_with_value_filter(self, cortellis_session):
        """Verify search can filter by deal value."""
        # Note: Finance values are stored in millions (e.g., 1000 = $1B)
        result = cortellis_session.execute(text("""
            SELECT d.id, d.title, f.total_projected_current_amount as value
            FROM deals d
            JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE f.total_projected_current_amount >= 1000
            ORDER BY f.total_projected_current_amount DESC
            LIMIT 10
        """))

        results = result.fetchall()
        assert len(results) > 0, "No billion-dollar deals found"
        for row in results:
            assert row.value >= 1000, \
                f"Deal value below threshold: {row.value}"

    def test_search_pagination(self, cortellis_session):
        """Verify search supports pagination."""
        # Get first page
        result1 = cortellis_session.execute(text("""
            SELECT id FROM deals
            ORDER BY id
            LIMIT 10 OFFSET 0
        """))
        page1 = [row.id for row in result1]

        # Get second page
        result2 = cortellis_session.execute(text("""
            SELECT id FROM deals
            ORDER BY id
            LIMIT 10 OFFSET 10
        """))
        page2 = [row.id for row in result2]

        assert len(page1) == 10, "First page incomplete"
        assert len(page2) == 10, "Second page incomplete"
        assert set(page1).isdisjoint(set(page2)), "Pages overlap"

    def test_search_sorting(self, cortellis_session):
        """Verify search supports sorting."""
        # Sort by date descending
        result = cortellis_session.execute(text("""
            SELECT id, date_start
            FROM deals
            WHERE date_start IS NOT NULL
            ORDER BY date_start DESC
            LIMIT 10
        """))

        dates = [row.date_start for row in result]
        for i in range(1, len(dates)):
            assert dates[i] <= dates[i-1], "Results not properly sorted"


@pytest.mark.integration
@pytest.mark.cortellis
class TestSearchPerformance:
    """Tests for search performance (should complete within thresholds)."""

    @pytest.mark.slow
    def test_fulltext_search_performance(self, cortellis_session):
        """Verify fulltext search completes in reasonable time."""
        import time

        query = "milestone payment"
        start = time.time()

        result = cortellis_session.execute(text("""
            SELECT cc.id
            FROM contract_chunks cc
            WHERE to_tsvector('english', cc.content) @@
                  plainto_tsquery('english', :query)
            LIMIT 100
        """), {"query": query})
        _ = result.fetchall()

        elapsed = time.time() - start
        # Should complete within 5 seconds with proper indexing
        assert elapsed < 5.0, f"Search took {elapsed:.2f}s (threshold: 5s)"

    @pytest.mark.slow
    def test_deal_search_performance(self, cortellis_session):
        """Verify deal search completes in reasonable time."""
        import time

        start = time.time()

        result = cortellis_session.execute(text("""
            SELECT
                d.id, d.title, d.deal_type, d.status, d.date_start,
                f.total_projected_current_amount
            FROM deals d
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE d.date_start >= '2020-01-01'
            ORDER BY d.date_start DESC
            LIMIT 100
        """))
        _ = result.fetchall()

        elapsed = time.time() - start
        # Should complete within 2 seconds
        assert elapsed < 2.0, f"Deal search took {elapsed:.2f}s (threshold: 2s)"
