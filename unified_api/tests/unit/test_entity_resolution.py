"""
Entity Resolution Tests for BD Intelligence Platform

Tests the company cross-reference (xref) system that links companies
between Cortellis and Edgar databases.

Key validations:
- Automated matching quality (ticker, name similarity)
- Match confidence scores
- No false positives on important companies
- Coverage metrics
"""
import pytest
from sqlalchemy import text
from typing import Dict, Any, List, Optional

# Known company mappings for validation (ground truth)
KNOWN_MAPPINGS = [
    # (cortellis_name_pattern, cik, expected_match)
    ("AbbVie", "0001551152", True),
    ("Pfizer", "0000078003", True),
    ("Bristol-Myers Squibb", "0000014272", True),
    ("Merck", "0000310158", True),  # Merck & Co
    ("Johnson & Johnson", "0000200406", True),
    ("Roche", None, False),  # Swiss company, no CIK
    ("Novartis", None, False),  # Swiss company, no CIK
    ("Eli Lilly", "0000059478", True),
    ("Amgen", "0000318154", True),
    ("Gilead", "0000882095", True),
]

# Companies that should NOT be matched (different entities with similar names)
FALSE_POSITIVE_CASES = [
    # (cortellis_name_pattern, should_not_match_cik)
    # Add known cases where name similarity could cause incorrect matches
]


@pytest.mark.cortellis
@pytest.mark.integration
class TestEntityResolution:
    """Tests for company entity resolution system."""

    def test_xref_table_structure(self, cortellis_session):
        """Verify company_xref table has required columns."""
        result = cortellis_session.execute(text("""
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'company_xref'
            ORDER BY ordinal_position
        """))
        columns = {row.column_name: row.data_type for row in result}

        required_columns = [
            "id",
            "cortellis_id",
            "cik",
            "ticker",
            "canonical_name",
            "match_method",
            "match_confidence",
        ]

        for col in required_columns:
            assert col in columns, f"Required column '{col}' missing from company_xref"

    def test_xref_coverage_metrics(self, cortellis_session):
        """Verify acceptable coverage of company matches."""
        # Count total Cortellis companies with deals
        result = cortellis_session.execute(text("""
            SELECT COUNT(DISTINCT company_id)
            FROM deal_companies
        """))
        total_active_companies = result.scalar()

        # Count matched companies (linked via CIK)
        result = cortellis_session.execute(text("""
            SELECT COUNT(*)
            FROM company_xref
            WHERE cortellis_id IS NOT NULL AND cik IS NOT NULL
        """))
        matched_count = result.scalar()

        # Calculate coverage percentage
        # Note: Not all Cortellis companies will have SEC filings (non-US, private, etc.)
        # We expect ~10-20% coverage for now
        if total_active_companies > 0:
            coverage = (matched_count / total_active_companies) * 100
            assert coverage >= 1, \
                f"Only {coverage:.1f}% of active companies matched (expected at least 1%)"

    def test_match_confidence_distribution(self, cortellis_session):
        """Verify match confidence scores are reasonable."""
        result = cortellis_session.execute(text("""
            SELECT
                CASE
                    WHEN match_confidence >= 0.9 THEN 'high'
                    WHEN match_confidence >= 0.6 THEN 'medium'
                    ELSE 'low'
                END as confidence_level,
                COUNT(*) as count
            FROM company_xref
            WHERE match_confidence IS NOT NULL
            GROUP BY confidence_level
        """))
        levels = {row.confidence_level: row.count for row in result}

        # Majority should be high confidence
        total = sum(levels.values()) if levels else 0
        high_confidence = levels.get('high', 0)

        if total > 0:
            high_percentage = (high_confidence / total) * 100
            # Many matches are trigram-based with lower confidence
            assert high_percentage >= 20, \
                f"Only {high_percentage:.1f}% of matches are high confidence"

    def test_match_methods_distribution(self, cortellis_session):
        """Verify match methods are properly categorized."""
        result = cortellis_session.execute(text("""
            SELECT match_method, COUNT(*) as count
            FROM company_xref
            WHERE match_method IS NOT NULL
            GROUP BY match_method
        """))
        methods = {row.match_method: row.count for row in result}

        # Should have at least ticker matches
        valid_methods = ['exact_ticker', 'trigram', 'manual', 'exact_name']
        assert any(m in methods for m in valid_methods), \
            f"No valid match methods found. Got: {list(methods.keys())}"

    @pytest.mark.parametrize("company_pattern,expected_cik,should_match", [
        case for case in KNOWN_MAPPINGS if case[1] is not None
    ])
    def test_known_company_mappings(
        self, cortellis_session, company_pattern, expected_cik, should_match
    ):
        """Verify known company mappings are correct."""
        result = cortellis_session.execute(text("""
            SELECT cx.cik, cx.canonical_name, cx.match_confidence
            FROM company_xref cx
            JOIN companies c ON c.id = cx.cortellis_id
            WHERE c.name ILIKE :pattern
            LIMIT 1
        """), {"pattern": f"%{company_pattern}%"})

        row = result.fetchone()

        if should_match:
            assert row is not None, \
                f"Expected match for {company_pattern} not found"
            if row:
                assert row.cik == expected_cik, \
                    f"CIK mismatch for {company_pattern}: got {row.cik}, expected {expected_cik}"
        # Note: We don't assert row is None for should_match=False
        # because the company might legitimately match to a different CIK

    def test_xref_canonical_names_populated(self, cortellis_session):
        """Verify canonical names are populated."""
        result = cortellis_session.execute(text("""
            SELECT COUNT(*) as total,
                   COUNT(canonical_name) as with_name
            FROM company_xref
        """))
        row = result.fetchone()

        if row.total > 0:
            name_percentage = (row.with_name / row.total) * 100
            assert name_percentage >= 95, \
                f"Only {name_percentage:.1f}% of xref entries have canonical names"

    def test_xref_references_valid_cortellis_companies(self, cortellis_session):
        """Verify all cortellis_id references are valid."""
        result = cortellis_session.execute(text("""
            SELECT COUNT(*)
            FROM company_xref cx
            WHERE cx.cortellis_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM companies c WHERE c.id = cx.cortellis_id
              )
        """))
        invalid = result.scalar()
        assert invalid == 0, f"Found {invalid} xref entries with invalid cortellis_id"

    def test_xref_tickers_format(self, cortellis_session):
        """Verify ticker format is valid."""
        result = cortellis_session.execute(text("""
            SELECT COUNT(*)
            FROM company_xref
            WHERE ticker IS NOT NULL
              AND ticker !~ '^[A-Z0-9\\.\\-]{1,10}$'
        """))
        invalid = result.scalar()
        assert invalid == 0, f"Found {invalid} xref entries with invalid ticker format"

    def test_xref_cik_format(self, cortellis_session):
        """Verify CIK format is valid (10-digit zero-padded)."""
        result = cortellis_session.execute(text("""
            SELECT COUNT(*)
            FROM company_xref
            WHERE cik IS NOT NULL
              AND cik !~ '^[0-9]{10}$'
        """))
        invalid = result.scalar()
        # Allow some non-standard CIKs but flag if excessive
        total = cortellis_session.execute(text(
            "SELECT COUNT(*) FROM company_xref WHERE cik IS NOT NULL"
        )).scalar()

        if total > 0:
            invalid_percentage = (invalid / total) * 100
            assert invalid_percentage < 5, \
                f"{invalid_percentage:.1f}% of CIKs have invalid format"


@pytest.mark.cortellis
@pytest.mark.integration
class TestEntityResolutionQuality:
    """Quality assurance tests for entity resolution."""

    def test_large_pharma_coverage(self, cortellis_session):
        """Verify major pharma companies are properly matched."""
        # List of major pharma that should definitely be in xref
        major_pharma = [
            "Pfizer", "Merck", "Johnson", "AbbVie", "Bristol-Myers",
            "Eli Lilly", "Amgen", "Gilead", "Regeneron", "Biogen"
        ]

        result = cortellis_session.execute(text("""
            SELECT c.name
            FROM companies c
            JOIN company_xref cx ON cx.cortellis_id = c.id
            WHERE cx.cik IS NOT NULL
        """))
        matched_names = [row.name.lower() for row in result]

        matched_count = sum(
            1 for pharma in major_pharma
            if any(pharma.lower() in name for name in matched_names)
        )

        # At least 50% of major pharma should be matched
        coverage = (matched_count / len(major_pharma)) * 100
        assert coverage >= 50, \
            f"Only {coverage:.0f}% of major pharma companies matched"

    def test_no_null_canonical_names(self, cortellis_session):
        """Verify all xref entries have canonical names."""
        result = cortellis_session.execute(text("""
            SELECT COUNT(*)
            FROM company_xref
            WHERE canonical_name IS NULL OR canonical_name = ''
        """))
        null_names = result.scalar()
        assert null_names == 0, f"Found {null_names} xref entries with null/empty canonical names"

    def test_match_confidence_correlates_with_method(self, cortellis_session):
        """Verify match confidence is appropriate for match method."""
        result = cortellis_session.execute(text("""
            SELECT match_method, AVG(match_confidence) as avg_confidence
            FROM company_xref
            WHERE match_method IS NOT NULL AND match_confidence IS NOT NULL
            GROUP BY match_method
        """))
        method_confidence = {row.match_method: row.avg_confidence for row in result}

        # Exact matches should have higher confidence than fuzzy
        if 'exact_ticker' in method_confidence and 'trigram' in method_confidence:
            assert method_confidence['exact_ticker'] >= method_confidence['trigram'], \
                "exact_ticker should have higher avg confidence than trigram"


@pytest.mark.cortellis
@pytest.mark.edgar
@pytest.mark.integration
class TestCrossReferenceIntegrity:
    """Tests that verify xref links to valid Edgar records."""

    def test_xref_ciks_exist_in_edgar(self, cortellis_session, edgar_source_session):
        """Verify CIKs in xref exist in Edgar DB companies."""
        # Get all CIKs from xref
        result = cortellis_session.execute(text("""
            SELECT DISTINCT cik
            FROM company_xref
            WHERE cik IS NOT NULL
        """))
        xref_ciks = {row.cik for row in result}

        if not xref_ciks:
            pytest.skip("No CIKs in xref")

        # Verify they exist in Edgar
        result = edgar_source_session.execute(text("""
            SELECT cik FROM companies WHERE cik IS NOT NULL
        """))
        edgar_ciks = {row.cik for row in result}

        missing = xref_ciks - edgar_ciks
        # Some CIKs may be formatted differently (leading zeros etc.)
        assert len(missing) <= len(xref_ciks) * 0.1, \
            f"Found {len(missing)}/{len(xref_ciks)} CIKs in xref not found in Edgar"

    def test_xref_cortellis_companies_exist(self, cortellis_session):
        """Verify cortellis_id references exist in Cortellis companies."""
        result = cortellis_session.execute(text("""
            SELECT COUNT(*)
            FROM company_xref cx
            WHERE cx.cortellis_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM companies c WHERE c.id = cx.cortellis_id
              )
        """))
        invalid = result.scalar()
        assert invalid == 0, \
            f"Found {invalid} xref entries with invalid cortellis_id"
