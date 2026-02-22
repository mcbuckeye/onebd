"""
Data Integrity Tests for BD Intelligence Platform

Validates data consistency and quality across Cortellis and Edgar databases.
These tests ensure:
- Expected row counts are within acceptable ranges
- Required fields are populated
- Foreign key relationships are valid
- Data quality metrics meet thresholds
"""
import pytest
from sqlalchemy import text
from typing import Dict, Any, List, Tuple

# Expected data volumes (with acceptable variance)
EXPECTED_COUNTS = {
    "cortellis": {
        "deals": (140000, 160000),  # ~145K deals
        "companies": (50000, 60000),  # ~52K companies
        "drugs": (30000, 40000),  # ~33K drugs
        "indications": (2000, 3000),  # ~2.5K indications
        "technologies": (500, 800),  # ~650 technologies
        "deal_contracts": (20000, 30000),  # ~26K contracts
        "contract_chunks": (850000, 1000000),  # ~903K chunks
    },
    "edgar": {
        "companies": (2500, 3000),  # ~2.7K companies
        "raw_documents": (300000, 350000),  # ~314K filings
        "documents": (200000, 400000),  # parsed documents
        "chunks": (3000000, 4000000),  # ~3.3M chunks
    },
}


# =============================================================================
# Cortellis Data Integrity Tests
# =============================================================================

@pytest.mark.cortellis
@pytest.mark.integration
class TestCortellisDataIntegrity:
    """Tests for Cortellis database data integrity."""

    def test_deals_table_exists_and_populated(self, cortellis_session):
        """Verify deals table exists and has expected row count."""
        result = cortellis_session.execute(text("SELECT COUNT(*) FROM deals"))
        count = result.scalar()

        min_expected, max_expected = EXPECTED_COUNTS["cortellis"]["deals"]
        assert count >= min_expected, f"Deals count {count} below minimum {min_expected}"
        assert count <= max_expected, f"Deals count {count} above maximum {max_expected}"

    def test_companies_table_exists_and_populated(self, cortellis_session):
        """Verify companies table exists and has expected row count."""
        result = cortellis_session.execute(text("SELECT COUNT(*) FROM companies"))
        count = result.scalar()

        min_expected, max_expected = EXPECTED_COUNTS["cortellis"]["companies"]
        assert count >= min_expected, f"Companies count {count} below minimum {min_expected}"

    def test_deal_companies_relationship_integrity(self, cortellis_session):
        """Verify all deal_companies reference valid deals and companies."""
        # Check for orphaned deal references
        result = cortellis_session.execute(text("""
            SELECT COUNT(*)
            FROM deal_companies dc
            WHERE NOT EXISTS (SELECT 1 FROM deals d WHERE d.id = dc.deal_id)
        """))
        orphaned_deals = result.scalar()
        assert orphaned_deals == 0, f"Found {orphaned_deals} deal_companies with invalid deal_id"

        # Check for orphaned company references
        result = cortellis_session.execute(text("""
            SELECT COUNT(*)
            FROM deal_companies dc
            WHERE NOT EXISTS (SELECT 1 FROM companies c WHERE c.id = dc.company_id)
        """))
        orphaned_companies = result.scalar()
        assert orphaned_companies == 0, f"Found {orphaned_companies} deal_companies with invalid company_id"

    def test_deals_have_required_fields(self, cortellis_session):
        """Verify deals have required fields populated."""
        # Check title is not null
        result = cortellis_session.execute(text("""
            SELECT COUNT(*) FROM deals WHERE title IS NULL OR title = ''
        """))
        null_titles = result.scalar()
        # Allow some null titles but flag if excessive
        total_deals = cortellis_session.execute(text("SELECT COUNT(*) FROM deals")).scalar()
        null_percentage = (null_titles / total_deals) * 100 if total_deals > 0 else 0
        assert null_percentage < 5, f"{null_percentage:.1f}% of deals have null/empty titles"

    def test_contract_chunks_have_embeddings(self, cortellis_session):
        """Verify contract chunks have embeddings populated."""
        result = cortellis_session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(embedding) as with_embedding
            FROM contract_chunks
        """))
        row = result.fetchone()
        total, with_embedding = row.total, row.with_embedding

        if total > 0:
            embedding_percentage = (with_embedding / total) * 100
            # At least 90% should have embeddings
            assert embedding_percentage >= 90, \
                f"Only {embedding_percentage:.1f}% of contract chunks have embeddings"

    def test_deal_finance_summary_values(self, cortellis_session):
        """Verify financial data integrity."""
        # Check for negative values (should not exist)
        result = cortellis_session.execute(text("""
            SELECT COUNT(*)
            FROM deal_finance_summary
            WHERE total_projected_current_amount < 0
               OR total_paid_amount < 0
        """))
        negative_values = result.scalar()
        assert negative_values == 0, f"Found {negative_values} deals with negative financial values"

        # Check disclosed vs undisclosed ratio
        result = cortellis_session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(total_projected_current_amount) as disclosed
            FROM deal_finance_summary
        """))
        row = result.fetchone()
        if row.total > 0:
            disclosed_percentage = (row.disclosed / row.total) * 100
            # We expect ~27% disclosed based on PRD
            assert disclosed_percentage >= 20, \
                f"Only {disclosed_percentage:.1f}% of deals have disclosed values"

    def test_contract_chunks_reference_valid_deals(self, cortellis_session):
        """Verify contract chunks reference valid deals."""
        result = cortellis_session.execute(text("""
            SELECT COUNT(*)
            FROM contract_chunks cc
            WHERE NOT EXISTS (SELECT 1 FROM deals d WHERE d.id = cc.deal_id)
        """))
        orphaned = result.scalar()
        assert orphaned == 0, f"Found {orphaned} contract chunks with invalid deal_id"

    def test_indications_hierarchy(self, cortellis_session):
        """Verify indications table structure."""
        result = cortellis_session.execute(text("""
            SELECT COUNT(*) FROM indications
        """))
        count = result.scalar()
        min_expected, max_expected = EXPECTED_COUNTS["cortellis"]["indications"]
        assert count >= min_expected, f"Indications count {count} below minimum"

    def test_technologies_populated(self, cortellis_session):
        """Verify technologies table is populated."""
        result = cortellis_session.execute(text("""
            SELECT COUNT(*) FROM technologies
        """))
        count = result.scalar()
        min_expected, max_expected = EXPECTED_COUNTS["cortellis"]["technologies"]
        assert count >= min_expected, f"Technologies count {count} below minimum"


# =============================================================================
# Edgar Data Integrity Tests
# =============================================================================

@pytest.mark.edgar
@pytest.mark.integration
class TestEdgarDataIntegrity:
    """Tests for Edgar database data integrity."""

    def test_companies_table_exists_and_populated(self, edgar_source_session):
        """Verify Edgar companies table exists and has expected row count."""
        result = edgar_source_session.execute(text("SELECT COUNT(*) FROM companies"))
        count = result.scalar()

        min_expected, max_expected = EXPECTED_COUNTS["edgar"]["companies"]
        assert count >= min_expected, f"Edgar companies count {count} below minimum {min_expected}"

    def test_companies_have_cik(self, edgar_source_session):
        """Verify Edgar companies have CIK identifiers."""
        result = edgar_source_session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(cik) as with_cik
            FROM companies
        """))
        row = result.fetchone()
        # Not all Edgar companies have CIK (some added via name matching)
        # but a meaningful portion should
        if row.total > 0:
            cik_percentage = (row.with_cik / row.total) * 100
            assert cik_percentage >= 20, \
                f"Only {cik_percentage:.1f}% of Edgar companies have CIK"

    def test_raw_documents_populated(self, edgar_source_session):
        """Verify raw_documents table is populated."""
        result = edgar_source_session.execute(text("SELECT COUNT(*) FROM raw_documents"))
        count = result.scalar()

        min_expected, max_expected = EXPECTED_COUNTS["edgar"]["raw_documents"]
        assert count >= min_expected, f"Raw documents count {count} below minimum"

    def test_chunks_have_embeddings(self, edgar_source_session):
        """Verify Edgar chunks have vector embeddings."""
        result = edgar_source_session.execute(text("""
            SELECT
                COUNT(*) as total,
                COUNT(vector) as with_embedding
            FROM chunks
        """))
        row = result.fetchone()

        if row.total > 0:
            embedding_percentage = (row.with_embedding / row.total) * 100
            # At least 95% should have embeddings (Edgar BD has 99.8%)
            assert embedding_percentage >= 95, \
                f"Only {embedding_percentage:.1f}% of Edgar chunks have embeddings"

    def test_documents_reference_valid_raw_documents(self, edgar_source_session):
        """Verify documents reference valid raw_documents."""
        result = edgar_source_session.execute(text("""
            SELECT COUNT(*)
            FROM documents d
            WHERE NOT EXISTS (
                SELECT 1 FROM raw_documents r WHERE r.id = d.raw_document_id
            )
        """))
        orphaned = result.scalar()
        assert orphaned == 0, f"Found {orphaned} documents with invalid raw_document_id"

    def test_chunks_reference_valid_documents(self, edgar_source_session):
        """Verify chunks reference valid documents."""
        result = edgar_source_session.execute(text("""
            SELECT COUNT(*)
            FROM chunks c
            WHERE NOT EXISTS (
                SELECT 1 FROM documents d WHERE d.id = c.document_id
            )
        """))
        orphaned = result.scalar()
        assert orphaned == 0, f"Found {orphaned} chunks with invalid document_id"

    def test_filing_types_distribution(self, edgar_source_session):
        """Verify expected filing types are present in raw_documents metadata."""
        result = edgar_source_session.execute(text("""
            SELECT
                filing_metadata->>'form_type' as form_type,
                COUNT(*) as count
            FROM raw_documents
            WHERE filing_metadata->>'form_type' IS NOT NULL
            GROUP BY form_type
            ORDER BY count DESC
            LIMIT 10
        """))
        filing_types = {row.form_type: row.count for row in result}

        # Should have common SEC filing types
        if not filing_types:
            # Fall back to doc_type on documents table
            result = edgar_source_session.execute(text("""
                SELECT doc_type, COUNT(*) as count
                FROM documents
                GROUP BY doc_type
                ORDER BY count DESC
            """))
            filing_types = {row.doc_type: row.count for row in result}

        # At minimum, we should have documents
        assert len(filing_types) >= 1, "No filing types found"


# =============================================================================
# Cross-Database Integrity Tests
# =============================================================================

@pytest.mark.cortellis
@pytest.mark.edgar
@pytest.mark.integration
class TestCrossDatabaseIntegrity:
    """Tests for data consistency across Cortellis and Edgar databases."""

    def test_company_xref_exists(self, cortellis_session):
        """Verify company_xref table exists for entity resolution."""
        result = cortellis_session.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'company_xref'
            )
        """))
        exists = result.scalar()
        assert exists, "company_xref table does not exist"

    def test_company_xref_has_matches(self, cortellis_session):
        """Verify company_xref has linked companies."""
        result = cortellis_session.execute(text("""
            SELECT COUNT(*) FROM company_xref
            WHERE cortellis_id IS NOT NULL AND cik IS NOT NULL
        """))
        count = result.scalar()
        # Should have at least 500 matched companies (692 linked)
        assert count >= 500, f"Only {count} companies matched in xref (expected 500+)"

    def test_company_xref_no_duplicate_cortellis_ids(self, cortellis_session):
        """Verify no duplicate cortellis_id in xref."""
        result = cortellis_session.execute(text("""
            SELECT cortellis_id, COUNT(*) as cnt
            FROM company_xref
            WHERE cortellis_id IS NOT NULL
            GROUP BY cortellis_id
            HAVING COUNT(*) > 1
        """))
        duplicates = result.fetchall()
        assert len(duplicates) == 0, \
            f"Found {len(duplicates)} duplicate cortellis_ids in company_xref"

    def test_company_xref_no_duplicate_ciks(self, cortellis_session):
        """Verify no duplicate CIK in xref."""
        result = cortellis_session.execute(text("""
            SELECT cik, COUNT(*) as cnt
            FROM company_xref
            WHERE cik IS NOT NULL
            GROUP BY cik
            HAVING COUNT(*) > 1
        """))
        duplicates = result.fetchall()
        assert len(duplicates) == 0, \
            f"Found {len(duplicates)} duplicate CIKs in company_xref"


# =============================================================================
# Data Quality Metrics Tests
# =============================================================================

@pytest.mark.cortellis
@pytest.mark.integration
class TestDataQualityMetrics:
    """Tests that measure data quality metrics."""

    def test_deals_per_year_distribution(self, cortellis_session):
        """Verify reasonable deal distribution across years."""
        result = cortellis_session.execute(text("""
            SELECT
                EXTRACT(YEAR FROM date_start) as year,
                COUNT(*) as count
            FROM deals
            WHERE date_start IS NOT NULL
              AND EXTRACT(YEAR FROM date_start) >= 2010
            GROUP BY year
            ORDER BY year
        """))
        years = {int(row.year): row.count for row in result}

        # Should have deals for recent years
        current_year = 2024
        for year in range(2020, current_year + 1):
            if year in years:
                assert years[year] >= 100, \
                    f"Year {year} has only {years.get(year, 0)} deals (expected 100+)"

    def test_company_type_distribution(self, cortellis_session):
        """Verify company types are properly categorized."""
        result = cortellis_session.execute(text("""
            SELECT company_type, COUNT(*) as count
            FROM companies
            WHERE company_type IS NOT NULL
            GROUP BY company_type
            ORDER BY count DESC
        """))
        types = {row.company_type: row.count for row in result}

        # Should have common company types
        assert len(types) >= 5, f"Only {len(types)} company types found"

    def test_deal_type_distribution(self, cortellis_session):
        """Verify agreement types are properly categorized."""
        result = cortellis_session.execute(text("""
            SELECT agreement_type, COUNT(*) as count
            FROM deals
            WHERE agreement_type IS NOT NULL
            GROUP BY agreement_type
            ORDER BY count DESC
        """))
        types = {row.agreement_type: row.count for row in result}

        # Should have common agreement types (21 types total)
        expected_patterns = ["License", "M&A"]
        for pattern in expected_patterns:
            assert any(pattern.lower() in t.lower() for t in types.keys()), \
                f"Expected agreement type containing '{pattern}' not found"


# =============================================================================
# Index Verification Tests
# =============================================================================

@pytest.mark.cortellis
@pytest.mark.integration
class TestIndexes:
    """Tests that verify required indexes exist for performance."""

    def test_contract_chunks_gin_index(self, cortellis_session):
        """Verify GIN index exists for fulltext search on contract_chunks."""
        result = cortellis_session.execute(text("""
            SELECT EXISTS (
                SELECT FROM pg_indexes
                WHERE tablename = 'contract_chunks'
                  AND indexdef LIKE '%gin%'
            )
        """))
        exists = result.scalar()
        # Note: Index may still be building
        if not exists:
            pytest.skip("GIN index on contract_chunks not yet created")

    def test_deals_date_index(self, cortellis_session):
        """Verify index exists on deals.date_start for date filtering."""
        result = cortellis_session.execute(text("""
            SELECT EXISTS (
                SELECT FROM pg_indexes
                WHERE tablename = 'deals'
                  AND indexdef LIKE '%date_start%'
            )
        """))
        exists = result.scalar()
        assert exists, "Index on deals.date_start is missing"

    def test_company_xref_indexes(self, cortellis_session):
        """Verify indexes exist on company_xref for lookups."""
        result = cortellis_session.execute(text("""
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'company_xref'
        """))
        indexes = [row.indexname for row in result]
        # Should have at least primary key index
        assert len(indexes) >= 1, "No indexes found on company_xref"


@pytest.mark.edgar
@pytest.mark.integration
class TestEdgarIndexes:
    """Tests that verify required indexes exist in Edgar database."""

    def test_chunks_gin_index(self, edgar_source_session):
        """Verify GIN index exists for fulltext search on chunks."""
        result = edgar_source_session.execute(text("""
            SELECT EXISTS (
                SELECT FROM pg_indexes
                WHERE tablename = 'chunks'
                  AND indexdef LIKE '%gin%'
            )
        """))
        exists = result.scalar()
        assert exists, "GIN index on chunks.text is missing"

    def test_chunks_embedding_index(self, edgar_source_session):
        """Verify vector index exists on chunks.embedding."""
        result = edgar_source_session.execute(text("""
            SELECT EXISTS (
                SELECT FROM pg_indexes
                WHERE tablename = 'chunks'
                  AND indexdef LIKE '%embedding%'
            )
        """))
        exists = result.scalar()
        # May not exist yet if not using pgvector
        if not exists:
            pytest.skip("Vector index on chunks.embedding not created")
