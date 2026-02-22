"""
Entity Resolution Service

Links companies between Cortellis and Edgar BD databases using:
- Exact ticker matching
- CIK matching
- Trigram fuzzy name matching

Creates and manages the company_xref cross-reference table.
"""
import re
from dataclasses import dataclass
from typing import Optional, List, Tuple

from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session, get_edgar_session

logger = structlog.get_logger(__name__)


def format_cik(cik: str) -> Optional[str]:
    """Format CIK as 10-digit zero-padded string."""
    if not cik:
        return None
    # Remove any non-numeric characters
    cik_clean = re.sub(r'\D', '', str(cik))
    if not cik_clean:
        return None
    # Pad to 10 digits
    return cik_clean.zfill(10)


@dataclass
class CompanyMatch:
    """Represents a potential match between companies"""
    cortellis_id: Optional[int]
    edgar_company_id: Optional[int]
    cik: Optional[str]
    ticker: Optional[str]
    cortellis_name: Optional[str]
    edgar_name: Optional[str]
    canonical_name: str
    match_method: str  # 'exact_ticker', 'exact_cik', 'trigram', 'manual'
    match_confidence: float  # 0.0 to 1.0


class EntityResolutionService:
    """Service for resolving company identities across databases"""

    # Minimum trigram similarity threshold for matching
    TRIGRAM_THRESHOLD = 0.6

    # Common suffixes to normalize company names
    COMPANY_SUFFIXES = [
        r'\s+Inc\.?$',
        r'\s+Corp\.?$',
        r'\s+Corporation$',
        r'\s+Ltd\.?$',
        r'\s+Limited$',
        r'\s+LLC$',
        r'\s+L\.L\.C\.?$',
        r'\s+PLC$',
        r'\s+P\.L\.C\.?$',
        r'\s+Co\.?$',
        r'\s+Company$',
        r'\s+SA$',
        r'\s+S\.A\.?$',
        r'\s+AG$',
        r'\s+A\.G\.?$',
        r'\s+GmbH$',
        r'\s+N\.V\.?$',
        r'\s+NV$',
        r'\s+BV$',
        r'\s+B\.V\.?$',
    ]

    def normalize_company_name(self, name: str) -> str:
        """
        Normalize a company name for comparison

        - Removes common suffixes (Inc, Corp, Ltd, etc.)
        - Converts to uppercase
        - Removes extra whitespace
        - Removes punctuation
        """
        if not name:
            return ""

        normalized = name.strip().upper()

        # Remove common suffixes
        for pattern in self.COMPANY_SUFFIXES:
            normalized = re.sub(pattern, '', normalized, flags=re.IGNORECASE)

        # Remove punctuation except ampersand
        normalized = re.sub(r'[^\w\s&]', '', normalized)

        # Collapse whitespace
        normalized = re.sub(r'\s+', ' ', normalized).strip()

        return normalized

    def create_company_xref_table(self, db_url: str):
        """
        Create the company_xref table in the specified database

        This table links company identities across Cortellis and Edgar BD.
        """
        from sqlalchemy import create_engine

        engine = create_engine(db_url)

        with engine.connect() as conn:
            # Enable pg_trgm extension for trigram similarity
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

            # Create the cross-reference table
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS company_xref (
                    id SERIAL PRIMARY KEY,

                    -- Cortellis identity
                    cortellis_id INTEGER UNIQUE,

                    -- Edgar BD identity
                    edgar_company_id INTEGER UNIQUE,
                    cik VARCHAR(10) UNIQUE,

                    -- Common identifiers
                    ticker VARCHAR(20),
                    canonical_name VARCHAR(500) NOT NULL,

                    -- Matching metadata
                    match_method VARCHAR(50),
                    match_confidence FLOAT,
                    manually_verified BOOLEAN DEFAULT FALSE,
                    verified_by VARCHAR(255),
                    verified_at TIMESTAMP,

                    -- Timestamps
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            """))

            # Create indexes
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_xref_ticker
                ON company_xref(ticker)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_xref_canonical_trgm
                ON company_xref USING gin (canonical_name gin_trgm_ops)
            """))

            conn.commit()

        logger.info("company_xref table created")

    def create_company_aliases_table(self, db_url: str):
        """
        Create the company_aliases table for historical name/ticker tracking
        """
        from sqlalchemy import create_engine

        engine = create_engine(db_url)

        with engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS company_aliases (
                    id SERIAL PRIMARY KEY,
                    xref_id INTEGER REFERENCES company_xref(id) ON DELETE CASCADE,
                    alias_type VARCHAR(50),  -- 'ticker', 'name', 'trade_name'
                    alias_value VARCHAR(500),
                    effective_from DATE,
                    effective_to DATE,
                    source VARCHAR(50),  -- 'sec', 'cortellis', 'manual'
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))

            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_aliases_xref
                ON company_aliases(xref_id)
            """))
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_aliases_value_trgm
                ON company_aliases USING gin (alias_value gin_trgm_ops)
            """))

            conn.commit()

        logger.info("company_aliases table created")

    def match_by_ticker(
        self,
        cortellis_companies: List[dict],
        edgar_companies: List[dict],
    ) -> List[CompanyMatch]:
        """
        Match companies by exact ticker symbol

        Args:
            cortellis_companies: List of dicts with 'id', 'name', 'ticker'
            edgar_companies: List of dicts with 'id', 'name', 'ticker', 'cik'

        Returns:
            List of CompanyMatch objects for exact ticker matches
        """
        matches = []

        # Build ticker lookup for Edgar companies
        edgar_by_ticker = {}
        for ec in edgar_companies:
            if ec.get('ticker'):
                ticker = ec['ticker'].upper().strip()
                edgar_by_ticker[ticker] = ec

        # Find matches
        for cc in cortellis_companies:
            if cc.get('ticker'):
                ticker = cc['ticker'].upper().strip()
                if ticker in edgar_by_ticker:
                    ec = edgar_by_ticker[ticker]
                    matches.append(CompanyMatch(
                        cortellis_id=cc['id'],
                        edgar_company_id=ec['id'],
                        cik=ec.get('cik'),
                        ticker=ticker,
                        cortellis_name=cc['name'],
                        edgar_name=ec['name'],
                        canonical_name=self.normalize_company_name(cc['name']),
                        match_method='exact_ticker',
                        match_confidence=1.0,
                    ))

        logger.info(f"Found {len(matches)} exact ticker matches")
        return matches

    def match_by_cik(
        self,
        cortellis_companies: List[dict],
        edgar_companies: List[dict],
    ) -> List[CompanyMatch]:
        """
        Match companies by CIK (if Cortellis has CIK data)

        This is less common since Cortellis typically doesn't have CIK.
        """
        matches = []

        # Build CIK lookup for Edgar companies
        edgar_by_cik = {}
        for ec in edgar_companies:
            if ec.get('cik'):
                cik = ec['cik'].lstrip('0').zfill(10)
                edgar_by_cik[cik] = ec

        # Check if Cortellis companies have CIK
        for cc in cortellis_companies:
            if cc.get('cik'):
                cik = cc['cik'].lstrip('0').zfill(10)
                if cik in edgar_by_cik:
                    ec = edgar_by_cik[cik]
                    matches.append(CompanyMatch(
                        cortellis_id=cc['id'],
                        edgar_company_id=ec['id'],
                        cik=cik,
                        ticker=ec.get('ticker') or cc.get('ticker'),
                        cortellis_name=cc['name'],
                        edgar_name=ec['name'],
                        canonical_name=self.normalize_company_name(cc['name']),
                        match_method='exact_cik',
                        match_confidence=1.0,
                    ))

        logger.info(f"Found {len(matches)} exact CIK matches")
        return matches

    def match_by_name_trigram(
        self,
        cortellis_name: str,
        threshold: float = None,
    ) -> List[Tuple[dict, float]]:
        """
        Find Edgar companies matching a Cortellis company name using trigram similarity

        Args:
            cortellis_name: Company name from Cortellis
            threshold: Minimum similarity threshold (default: TRIGRAM_THRESHOLD)

        Returns:
            List of (edgar_company_dict, similarity_score) tuples
        """
        if threshold is None:
            threshold = self.TRIGRAM_THRESHOLD

        normalized_name = self.normalize_company_name(cortellis_name)

        with get_edgar_session() as session:
            result = session.execute(text("""
                SELECT
                    id,
                    name,
                    ticker,
                    cik,
                    similarity(UPPER(name), :search_name) as sim
                FROM companies
                WHERE similarity(UPPER(name), :search_name) > :threshold
                ORDER BY sim DESC
                LIMIT 5
            """), {
                'search_name': normalized_name,
                'threshold': threshold,
            })

            matches = []
            for row in result:
                matches.append((
                    {
                        'id': row.id,
                        'name': row.name,
                        'ticker': row.ticker,
                        'cik': row.cik,
                    },
                    row.sim,
                ))

        return matches

    def auto_match_companies(self, batch_size: int = 1000) -> dict:
        """
        Run automatic matching between all Cortellis and Edgar companies

        Runs matching in priority order:
        1. Exact ticker match
        2. Exact CIK match
        3. Trigram name similarity

        Returns:
            Statistics about matching results
        """
        stats = {
            'cortellis_total': 0,
            'edgar_total': 0,
            'ticker_matches': 0,
            'cik_matches': 0,
            'trigram_matches': 0,
            'unmatched': 0,
        }

        # Fetch all companies from both databases
        with get_cortellis_session() as c_session:
            result = c_session.execute(text("""
                SELECT id, name, ticker
                FROM companies
                LIMIT :limit
            """), {'limit': batch_size})

            cortellis_companies = [
                {'id': r.id, 'name': r.name, 'ticker': r.ticker}
                for r in result
            ]
            stats['cortellis_total'] = len(cortellis_companies)

        with get_edgar_session() as e_session:
            result = e_session.execute(text("""
                SELECT id, name, ticker, cik
                FROM companies
            """))

            edgar_companies = [
                {'id': r.id, 'name': r.name, 'ticker': r.ticker, 'cik': r.cik}
                for r in result
            ]
            stats['edgar_total'] = len(edgar_companies)

        # Run matching
        all_matches = []

        # 1. Exact ticker matches
        ticker_matches = self.match_by_ticker(cortellis_companies, edgar_companies)
        all_matches.extend(ticker_matches)
        stats['ticker_matches'] = len(ticker_matches)

        # Track matched IDs to avoid duplicates
        matched_cortellis_ids = {m.cortellis_id for m in all_matches}
        matched_edgar_ids = {m.edgar_company_id for m in all_matches}

        # 2. CIK matches (for remaining companies)
        remaining_cortellis = [c for c in cortellis_companies if c['id'] not in matched_cortellis_ids]
        remaining_edgar = [e for e in edgar_companies if e['id'] not in matched_edgar_ids]

        cik_matches = self.match_by_cik(remaining_cortellis, remaining_edgar)
        all_matches.extend(cik_matches)
        stats['cik_matches'] = len(cik_matches)

        matched_cortellis_ids.update(m.cortellis_id for m in cik_matches)
        matched_edgar_ids.update(m.edgar_company_id for m in cik_matches)

        # 3. Trigram name matching (for remaining)
        remaining_cortellis = [c for c in cortellis_companies if c['id'] not in matched_cortellis_ids]

        trigram_count = 0
        for cc in remaining_cortellis:
            name_matches = self.match_by_name_trigram(cc['name'])
            if name_matches:
                best_match, similarity = name_matches[0]
                if best_match['id'] not in matched_edgar_ids:
                    all_matches.append(CompanyMatch(
                        cortellis_id=cc['id'],
                        edgar_company_id=best_match['id'],
                        cik=best_match.get('cik'),
                        ticker=best_match.get('ticker') or cc.get('ticker'),
                        cortellis_name=cc['name'],
                        edgar_name=best_match['name'],
                        canonical_name=self.normalize_company_name(cc['name']),
                        match_method='trigram',
                        match_confidence=similarity,
                    ))
                    matched_cortellis_ids.add(cc['id'])
                    matched_edgar_ids.add(best_match['id'])
                    trigram_count += 1

        stats['trigram_matches'] = trigram_count
        stats['unmatched'] = len(cortellis_companies) - len(matched_cortellis_ids)

        logger.info("Auto-matching completed", **stats)
        return {'stats': stats, 'matches': all_matches}

    def save_matches_to_xref(self, matches: List[CompanyMatch], db_url: str):
        """
        Save match results to the company_xref table

        Args:
            matches: List of CompanyMatch objects
            db_url: Database URL where company_xref table exists
        """
        from sqlalchemy import create_engine

        engine = create_engine(db_url)

        with engine.connect() as conn:
            for match in matches:
                conn.execute(text("""
                    INSERT INTO company_xref (
                        cortellis_id,
                        edgar_company_id,
                        cik,
                        ticker,
                        canonical_name,
                        match_method,
                        match_confidence
                    ) VALUES (
                        :cortellis_id,
                        :edgar_company_id,
                        :cik,
                        :ticker,
                        :canonical_name,
                        :match_method,
                        :match_confidence
                    )
                    ON CONFLICT (cortellis_id) DO UPDATE SET
                        edgar_company_id = EXCLUDED.edgar_company_id,
                        cik = EXCLUDED.cik,
                        ticker = EXCLUDED.ticker,
                        canonical_name = EXCLUDED.canonical_name,
                        match_method = EXCLUDED.match_method,
                        match_confidence = EXCLUDED.match_confidence,
                        updated_at = NOW()
                """), {
                    'cortellis_id': match.cortellis_id,
                    'edgar_company_id': match.edgar_company_id,
                    'cik': match.cik,
                    'ticker': match.ticker,
                    'canonical_name': match.canonical_name,
                    'match_method': match.match_method,
                    'match_confidence': match.match_confidence,
                })

            conn.commit()

        logger.info(f"Saved {len(matches)} matches to company_xref")

    def get_unified_company(
        self,
        cortellis_id: Optional[int] = None,
        cik: Optional[str] = None,
        ticker: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Look up a company from the unified cross-reference

        Args:
            cortellis_id: Cortellis company ID
            cik: SEC CIK number
            ticker: Stock ticker symbol

        Returns:
            Dict with unified company info or None if not found
        """
        conditions = []
        params = {}

        if cortellis_id:
            conditions.append("cx.cortellis_id = :cortellis_id")
            params['cortellis_id'] = cortellis_id
        if cik:
            conditions.append("cx.cik = :cik")
            params['cik'] = format_cik(cik)
        if ticker:
            conditions.append("UPPER(cx.ticker) = :ticker")
            params['ticker'] = ticker.upper()

        if not conditions:
            return None

        with get_cortellis_session() as session:
            result = session.execute(text(f"""
                SELECT
                    cx.*,
                    c.name,
                    c.company_type,
                    c.hq_location
                FROM company_xref cx
                JOIN companies c ON c.id = cx.cortellis_id
                WHERE {' OR '.join(conditions)}
                LIMIT 1
            """), params)

            row = result.fetchone()
            if row:
                return {
                    "xref_id": row.id,
                    "cortellis_id": row.cortellis_id,
                    "cik": row.cik,
                    "ticker": row.ticker,
                    "canonical_name": row.canonical_name,
                    "match_method": row.match_method,
                    "match_confidence": row.match_confidence,
                    "manually_verified": row.manually_verified,
                    "name": row.name,
                    "company_type": row.company_type,
                    "hq_location": row.hq_location,
                }

        return None

    def find_cortellis_match(
        self,
        name: str,
        ticker: Optional[str] = None,
        cik: Optional[str] = None,
        min_similarity: float = 0.6,
    ) -> Optional[CompanyMatch]:
        """
        Find the best matching Cortellis company for an external entity.

        Tries matching in order of confidence:
        1. CIK (if provided) - 100% confidence
        2. Ticker (if provided) - 100% confidence
        3. Exact name match - 100% confidence
        4. Trigram fuzzy match - variable confidence
        """
        # Try CIK first (most reliable)
        if cik:
            cik_formatted = format_cik(cik)
            with get_cortellis_session() as session:
                result = session.execute(text("""
                    SELECT id, name, ticker, cik
                    FROM companies
                    WHERE cik = :cik
                    LIMIT 1
                """), {"cik": cik_formatted})
                row = result.fetchone()
                if row:
                    return CompanyMatch(
                        cortellis_id=row.id,
                        edgar_company_id=None,
                        cik=row.cik,
                        ticker=row.ticker,
                        cortellis_name=row.name,
                        edgar_name=name,
                        canonical_name=self.normalize_company_name(row.name),
                        match_method="exact_cik",
                        match_confidence=1.0,
                    )

        # Try ticker
        if ticker:
            ticker_upper = ticker.upper().strip()
            with get_cortellis_session() as session:
                result = session.execute(text("""
                    SELECT id, name, ticker, cik
                    FROM companies
                    WHERE UPPER(ticker) = :ticker
                    LIMIT 1
                """), {"ticker": ticker_upper})
                row = result.fetchone()
                if row:
                    return CompanyMatch(
                        cortellis_id=row.id,
                        edgar_company_id=None,
                        cik=row.cik,
                        ticker=row.ticker,
                        cortellis_name=row.name,
                        edgar_name=name,
                        canonical_name=self.normalize_company_name(row.name),
                        match_method="exact_ticker",
                        match_confidence=1.0,
                    )

        # Try exact name match
        normalized = self.normalize_company_name(name)
        with get_cortellis_session() as session:
            result = session.execute(text("""
                SELECT id, name, ticker, cik
                FROM companies
                WHERE UPPER(name) = UPPER(:name)
                   OR UPPER(name) = :normalized
                LIMIT 1
            """), {"name": name, "normalized": normalized})
            row = result.fetchone()
            if row:
                return CompanyMatch(
                    cortellis_id=row.id,
                    edgar_company_id=None,
                    cik=row.cik,
                    ticker=row.ticker,
                    cortellis_name=row.name,
                    edgar_name=name,
                    canonical_name=self.normalize_company_name(row.name),
                    match_method="exact_name",
                    match_confidence=1.0,
                )

        # Try fuzzy match
        with get_cortellis_session() as session:
            result = session.execute(text("""
                SELECT
                    id, name, ticker, cik,
                    similarity(UPPER(name), :normalized) as sim
                FROM companies
                WHERE similarity(UPPER(name), :normalized) > :min_sim
                ORDER BY sim DESC
                LIMIT 1
            """), {"normalized": normalized, "min_sim": min_similarity})
            row = result.fetchone()
            if row:
                return CompanyMatch(
                    cortellis_id=row.id,
                    edgar_company_id=None,
                    cik=row.cik,
                    ticker=row.ticker,
                    cortellis_name=row.name,
                    edgar_name=name,
                    canonical_name=self.normalize_company_name(row.name),
                    match_method="trigram",
                    match_confidence=float(row.sim),
                )

        return None

    def create_xref(
        self,
        cortellis_id: int,
        cik: Optional[str] = None,
        ticker: Optional[str] = None,
        match_method: str = "manual",
        confidence: float = 1.0,
        verified: bool = False,
        verified_by: Optional[str] = None,
    ) -> int:
        """
        Create or update a company cross-reference entry.

        Returns the xref ID.
        """
        cik_formatted = format_cik(cik) if cik else None
        ticker_upper = ticker.upper().strip() if ticker else None

        with get_cortellis_session() as session:
            # Get the company name for canonical_name
            result = session.execute(text("""
                SELECT name FROM companies WHERE id = :id
            """), {"id": cortellis_id})
            company = result.fetchone()

            if not company:
                raise ValueError(f"Company {cortellis_id} not found")

            canonical_name = self.normalize_company_name(company.name)

            # Insert or update xref
            result = session.execute(text("""
                INSERT INTO company_xref (
                    cortellis_id, cik, ticker, canonical_name,
                    match_method, match_confidence,
                    manually_verified, verified_by, verified_at
                ) VALUES (
                    :cortellis_id, :cik, :ticker, :canonical_name,
                    :match_method, :confidence,
                    :verified, :verified_by,
                    CASE WHEN :verified THEN NOW() ELSE NULL END
                )
                ON CONFLICT (cortellis_id) DO UPDATE SET
                    cik = COALESCE(EXCLUDED.cik, company_xref.cik),
                    ticker = COALESCE(EXCLUDED.ticker, company_xref.ticker),
                    match_method = EXCLUDED.match_method,
                    match_confidence = EXCLUDED.match_confidence,
                    manually_verified = EXCLUDED.manually_verified,
                    verified_by = EXCLUDED.verified_by,
                    verified_at = EXCLUDED.verified_at,
                    updated_at = NOW()
                RETURNING id
            """), {
                "cortellis_id": cortellis_id,
                "cik": cik_formatted,
                "ticker": ticker_upper,
                "canonical_name": canonical_name,
                "match_method": match_method,
                "confidence": confidence,
                "verified": verified,
                "verified_by": verified_by,
            })

            xref_id = result.fetchone().id
            session.commit()

            # Also update the companies table for convenience
            session.execute(text("""
                UPDATE companies SET
                    cik = COALESCE(:cik, cik),
                    ticker = COALESCE(:ticker, ticker)
                WHERE id = :id
            """), {
                "id": cortellis_id,
                "cik": cik_formatted,
                "ticker": ticker_upper,
            })
            session.commit()

            logger.info(
                "Created company xref",
                xref_id=xref_id,
                cortellis_id=cortellis_id,
                cik=cik_formatted,
                ticker=ticker_upper,
            )

            return xref_id

    def get_matching_stats(self) -> dict:
        """Get statistics about entity resolution."""
        with get_cortellis_session() as session:
            result = session.execute(text("""
                SELECT
                    COUNT(*) as total_xrefs,
                    COUNT(cik) as with_cik,
                    COUNT(ticker) as with_ticker,
                    COUNT(CASE WHEN manually_verified THEN 1 END) as verified,
                    COUNT(CASE WHEN match_method = 'exact_ticker' THEN 1 END) as by_ticker,
                    COUNT(CASE WHEN match_method = 'exact_name' THEN 1 END) as by_name,
                    COUNT(CASE WHEN match_method = 'exact_cik' THEN 1 END) as by_cik,
                    COUNT(CASE WHEN match_method = 'trigram' THEN 1 END) as by_trigram,
                    COUNT(CASE WHEN match_method = 'manual' THEN 1 END) as by_manual,
                    AVG(match_confidence) as avg_confidence
                FROM company_xref
            """))
            row = result.fetchone()

            companies_result = session.execute(text("""
                SELECT
                    COUNT(*) as total_companies,
                    COUNT(cik) as with_cik,
                    COUNT(ticker) as with_ticker
                FROM companies
            """))
            companies = companies_result.fetchone()

            return {
                "companies": {
                    "total": companies.total_companies,
                    "with_cik": companies.with_cik,
                    "with_ticker": companies.with_ticker,
                },
                "xrefs": {
                    "total": row.total_xrefs,
                    "with_cik": row.with_cik,
                    "with_ticker": row.with_ticker,
                    "verified": row.verified,
                },
                "by_method": {
                    "cik": row.by_cik,
                    "ticker": row.by_ticker,
                    "name": row.by_name,
                    "trigram": row.by_trigram,
                    "manual": row.by_manual,
                },
                "avg_confidence": float(row.avg_confidence) if row.avg_confidence else 0,
            }

    def search_companies(
        self,
        query: str,
        limit: int = 20,
    ) -> List[dict]:
        """Search Cortellis companies by name with fuzzy matching."""
        normalized = self.normalize_company_name(query)

        with get_cortellis_session() as session:
            result = session.execute(text("""
                SELECT
                    c.id,
                    c.name,
                    c.company_type,
                    c.ticker,
                    c.cik,
                    similarity(UPPER(c.name), :normalized) as sim,
                    cx.id as xref_id
                FROM companies c
                LEFT JOIN company_xref cx ON cx.cortellis_id = c.id
                WHERE c.name ILIKE :pattern
                   OR similarity(UPPER(c.name), :normalized) > 0.3
                ORDER BY
                    CASE WHEN UPPER(c.name) = :normalized THEN 0 ELSE 1 END,
                    similarity(UPPER(c.name), :normalized) DESC
                LIMIT :limit
            """), {
                "normalized": normalized,
                "pattern": f"%{query}%",
                "limit": limit,
            })

            companies = []
            for row in result:
                companies.append({
                    "id": row.id,
                    "name": row.name,
                    "company_type": row.company_type,
                    "ticker": row.ticker,
                    "cik": row.cik,
                    "similarity": float(row.sim) if row.sim else 0,
                    "has_xref": row.xref_id is not None,
                })

            return companies


    def match_unmatched_edgar_companies(self, min_similarity: float = 0.6) -> dict:
        """
        Match Edgar companies that are NOT yet in company_xref against Cortellis.

        Uses trigram similarity for fuzzy name matching.

        Returns:
            Statistics about new matches created
        """
        stats = {
            'edgar_unmatched_checked': 0,
            'new_ticker_matches': 0,
            'new_trigram_matches': 0,
            'failed_to_match': 0,
            'new_xrefs_created': 0,
        }

        # Get all existing CIKs in company_xref
        with get_cortellis_session() as session:
            result = session.execute(text("""
                SELECT cik FROM company_xref WHERE cik IS NOT NULL
            """))
            existing_ciks = {row.cik for row in result}
            logger.info(f"Found {len(existing_ciks)} existing CIKs in company_xref")

        # Get unmatched Edgar companies (those with CIK not in xref)
        with get_edgar_session() as session:
            result = session.execute(text("""
                SELECT id, cik, name, ticker
                FROM companies
                WHERE cik IS NOT NULL AND cik <> ''
                ORDER BY name
            """))
            edgar_companies = []
            for row in result:
                cik_formatted = format_cik(row.cik)
                if cik_formatted and cik_formatted not in existing_ciks:
                    edgar_companies.append({
                        'id': row.id,
                        'cik': cik_formatted,
                        'name': row.name,
                        'ticker': row.ticker,
                    })

        stats['edgar_unmatched_checked'] = len(edgar_companies)
        logger.info(f"Found {len(edgar_companies)} unmatched Edgar companies to process")

        if not edgar_companies:
            logger.info("No unmatched Edgar companies to process")
            return stats

        # Try to match each Edgar company against Cortellis
        new_matches = []

        for ec in edgar_companies:
            match = None

            # Try ticker match first (highest confidence)
            if ec['ticker']:
                ticker_upper = ec['ticker'].upper().strip()
                with get_cortellis_session() as session:
                    result = session.execute(text("""
                        SELECT id, name, ticker
                        FROM companies
                        WHERE UPPER(ticker) = :ticker
                        LIMIT 1
                    """), {"ticker": ticker_upper})
                    row = result.fetchone()
                    if row:
                        match = CompanyMatch(
                            cortellis_id=row.id,
                            edgar_company_id=ec['id'],
                            cik=ec['cik'],
                            ticker=ticker_upper,
                            cortellis_name=row.name,
                            edgar_name=ec['name'],
                            canonical_name=self.normalize_company_name(row.name),
                            match_method='exact_ticker',
                            match_confidence=1.0,
                        )
                        stats['new_ticker_matches'] += 1

            # Try trigram name match if no ticker match
            if not match:
                normalized = self.normalize_company_name(ec['name'])
                with get_cortellis_session() as session:
                    result = session.execute(text("""
                        SELECT
                            id, name, ticker,
                            similarity(UPPER(name), :normalized) as sim
                        FROM companies
                        WHERE similarity(UPPER(name), :normalized) > :min_sim
                        ORDER BY sim DESC
                        LIMIT 1
                    """), {"normalized": normalized, "min_sim": min_similarity})
                    row = result.fetchone()
                    if row:
                        match = CompanyMatch(
                            cortellis_id=row.id,
                            edgar_company_id=ec['id'],
                            cik=ec['cik'],
                            ticker=ec['ticker'] or row.ticker,
                            cortellis_name=row.name,
                            edgar_name=ec['name'],
                            canonical_name=self.normalize_company_name(row.name),
                            match_method='trigram',
                            match_confidence=float(row.sim),
                        )
                        stats['new_trigram_matches'] += 1

            if match:
                new_matches.append(match)
            else:
                stats['failed_to_match'] += 1

        # Save new matches to company_xref
        if new_matches:
            with get_cortellis_session() as session:
                for match in new_matches:
                    try:
                        # Check if CIK already exists
                        existing = session.execute(text("""
                            SELECT id FROM company_xref WHERE cik = :cik
                        """), {'cik': match.cik})
                        if existing.fetchone():
                            logger.debug(f"CIK {match.cik} already in xref, skipping")
                            continue

                        # Check if cortellis_id already exists
                        existing = session.execute(text("""
                            SELECT id FROM company_xref WHERE cortellis_id = :cortellis_id
                        """), {'cortellis_id': match.cortellis_id})
                        if existing.fetchone():
                            # Update existing entry with CIK
                            session.execute(text("""
                                UPDATE company_xref SET
                                    cik = COALESCE(:cik, cik),
                                    ticker = COALESCE(:ticker, ticker),
                                    updated_at = NOW()
                                WHERE cortellis_id = :cortellis_id
                            """), {
                                'cortellis_id': match.cortellis_id,
                                'cik': match.cik,
                                'ticker': match.ticker,
                            })
                        else:
                            # Insert new entry
                            session.execute(text("""
                                INSERT INTO company_xref (
                                    cortellis_id, cik, ticker, canonical_name,
                                    match_method, match_confidence
                                ) VALUES (
                                    :cortellis_id, :cik, :ticker, :canonical_name,
                                    :match_method, :match_confidence
                                )
                            """), {
                                'cortellis_id': match.cortellis_id,
                                'cik': match.cik,
                                'ticker': match.ticker,
                                'canonical_name': match.canonical_name,
                                'match_method': match.match_method,
                                'match_confidence': match.match_confidence,
                            })
                        stats['new_xrefs_created'] += 1
                    except Exception as e:
                        # Might fail on unique constraints, that's OK
                        logger.warning(f"Failed to insert xref for {match.edgar_name}: {e}")

                session.commit()

        logger.info("Entity resolution completed", **stats)
        return stats

    def match_edgar_companies_by_name(self, min_similarity: float = 0.5) -> dict:
        """
        Match Edgar companies (even those WITHOUT CIK) against Cortellis by name.

        Useful for matching companies extracted from deal text that don't have SEC filings.

        Returns:
            Statistics about matches
        """
        stats = {
            'edgar_companies_checked': 0,
            'new_matches': 0,
            'already_matched': 0,
            'no_match': 0,
        }

        # Get Edgar companies without CIK (extracted from text)
        with get_edgar_session() as session:
            result = session.execute(text("""
                SELECT id, name, ticker
                FROM companies
                WHERE (cik IS NULL OR cik = '')
                ORDER BY name
            """))
            edgar_companies = [
                {'id': row.id, 'name': row.name, 'ticker': row.ticker}
                for row in result
            ]

        stats['edgar_companies_checked'] = len(edgar_companies)
        logger.info(f"Checking {len(edgar_companies)} Edgar companies without CIK")

        # For each, try to find a matching Cortellis company
        for ec in edgar_companies:
            normalized = self.normalize_company_name(ec['name'])

            with get_cortellis_session() as session:
                # Check if already matched via canonical_name
                result = session.execute(text("""
                    SELECT id FROM company_xref
                    WHERE similarity(UPPER(canonical_name), :normalized) > 0.9
                    LIMIT 1
                """), {"normalized": normalized})

                if result.fetchone():
                    stats['already_matched'] += 1
                    continue

                # Try to find a Cortellis match
                result = session.execute(text("""
                    SELECT
                        id, name, ticker,
                        similarity(UPPER(name), :normalized) as sim
                    FROM companies
                    WHERE similarity(UPPER(name), :normalized) > :min_sim
                    ORDER BY sim DESC
                    LIMIT 1
                """), {"normalized": normalized, "min_sim": min_similarity})

                row = result.fetchone()
                if row:
                    # Add to xref (without CIK since Edgar company doesn't have one)
                    try:
                        session.execute(text("""
                            INSERT INTO company_xref (
                                cortellis_id, ticker, canonical_name,
                                match_method, match_confidence
                            ) VALUES (
                                :cortellis_id, :ticker, :canonical_name,
                                'trigram', :confidence
                            )
                            ON CONFLICT (cortellis_id) DO NOTHING
                        """), {
                            'cortellis_id': row.id,
                            'ticker': ec['ticker'] or row.ticker,
                            'canonical_name': self.normalize_company_name(row.name),
                            'confidence': float(row.sim),
                        })
                        session.commit()
                        stats['new_matches'] += 1
                    except Exception as e:
                        logger.warning(f"Failed to insert xref: {e}")
                else:
                    stats['no_match'] += 1

        logger.info("Name-based matching completed", **stats)
        return stats


# Global service instance
_entity_resolution_service: Optional[EntityResolutionService] = None


def get_entity_resolution_service() -> EntityResolutionService:
    """Get or create the entity resolution service"""
    global _entity_resolution_service

    if _entity_resolution_service is None:
        _entity_resolution_service = EntityResolutionService()

    return _entity_resolution_service
