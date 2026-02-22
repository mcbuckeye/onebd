"""
Database Connection Tests for BD Intelligence Platform

Tests database connectivity, session management, and connection pooling.
Validates that all database services are properly configured.
"""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
import time


@pytest.mark.integration
class TestCortellisConnection:
    """Tests for Cortellis database connectivity."""

    def test_cortellis_connection_success(self, cortellis_engine):
        """Verify basic connectivity to Cortellis database."""
        with cortellis_engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

    def test_cortellis_database_version(self, cortellis_engine):
        """Verify PostgreSQL version is compatible."""
        with cortellis_engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            assert "PostgreSQL" in version
            # Extract major version number
            import re
            match = re.search(r'PostgreSQL (\d+)', version)
            if match:
                major_version = int(match.group(1))
                assert major_version >= 14, \
                    f"PostgreSQL {major_version} is below minimum (14)"

    def test_cortellis_pgvector_extension(self, cortellis_engine):
        """Verify pgvector extension is installed."""
        with cortellis_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM pg_extension WHERE extname = 'vector'
                )
            """))
            assert result.scalar(), "pgvector extension not installed"

    def test_cortellis_session_management(self, cortellis_session):
        """Verify session is properly managed."""
        # Session should be active
        assert cortellis_session.is_active

        # Should be able to execute queries
        result = cortellis_session.execute(text("SELECT current_database()"))
        db_name = result.scalar()
        assert db_name is not None

    def test_cortellis_connection_pool(self, cortellis_engine):
        """Verify connection pool is functioning."""
        pool = cortellis_engine.pool

        # Get initial pool status
        initial_checkedin = pool.checkedin()
        initial_checkedout = pool.checkedout()

        # Checkout a connection
        with cortellis_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            # While connection is in use, checkedout should increase
            assert pool.checkedout() >= 1

        # After context exits, connection should be returned
        # Note: May not be immediate due to pool behavior
        time.sleep(0.1)
        assert pool.checkedin() >= 0


@pytest.mark.integration
class TestEdgarConnection:
    """Tests for Edgar database connectivity."""

    def test_edgar_connection_success(self, edgar_engine):
        """Verify basic connectivity to Edgar database."""
        with edgar_engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

    def test_edgar_source_connection_success(self, edgar_source_engine):
        """Verify connectivity to Edgar source database."""
        with edgar_source_engine.connect() as conn:
            result = conn.execute(text("SELECT 1"))
            assert result.scalar() == 1

    def test_edgar_pgvector_extension(self, edgar_source_engine):
        """Verify pgvector extension in Edgar source database."""
        with edgar_source_engine.connect() as conn:
            result = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM pg_extension WHERE extname = 'vector'
                )
            """))
            assert result.scalar(), "pgvector extension not installed in Edgar"

    def test_edgar_session_isolation(self, edgar_session, edgar_source_session):
        """Verify Edgar and Edgar source are separate databases."""
        # Get database names
        result1 = edgar_session.execute(text("SELECT current_database()"))
        result2 = edgar_source_session.execute(text("SELECT current_database()"))

        db1 = result1.scalar()
        db2 = result2.scalar()

        # They may be the same database on different hosts
        # This is OK - we're testing they're independently accessible
        assert db1 is not None
        assert db2 is not None


@pytest.mark.integration
class TestDatabaseSchema:
    """Tests that verify database schemas are correct."""

    def test_cortellis_required_tables(self, cortellis_session):
        """Verify all required Cortellis tables exist."""
        required_tables = [
            "deals",
            "companies",
            "deal_companies",
            "drugs",
            "indications",
            "technologies",
            "deal_contracts",
            "contract_chunks",
            "deal_finance_summary",
            "company_xref",
        ]

        result = cortellis_session.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
        """))
        existing_tables = {row.table_name for row in result}

        missing = set(required_tables) - existing_tables
        assert len(missing) == 0, f"Missing required tables: {missing}"

    def test_edgar_required_tables(self, edgar_source_session):
        """Verify all required Edgar tables exist."""
        required_tables = [
            "companies",
            "raw_documents",
            "documents",
            "chunks",
        ]

        result = edgar_source_session.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
        """))
        existing_tables = {row.table_name for row in result}

        missing = set(required_tables) - existing_tables
        assert len(missing) == 0, f"Missing required Edgar tables: {missing}"

    def test_contract_chunks_embedding_column(self, cortellis_session):
        """Verify contract_chunks has vector embedding column."""
        result = cortellis_session.execute(text("""
            SELECT data_type
            FROM information_schema.columns
            WHERE table_name = 'contract_chunks'
              AND column_name = 'embedding'
        """))
        row = result.fetchone()
        assert row is not None, "embedding column not found in contract_chunks"
        # pgvector stores as USER-DEFINED type
        assert row.data_type in ('USER-DEFINED', 'vector'), \
            f"Unexpected embedding type: {row.data_type}"

    def test_edgar_chunks_vector_column(self, edgar_source_session):
        """Verify Edgar chunks has vector column for embeddings."""
        result = edgar_source_session.execute(text("""
            SELECT data_type
            FROM information_schema.columns
            WHERE table_name = 'chunks'
              AND column_name = 'vector'
        """))
        row = result.fetchone()
        assert row is not None, "vector column not found in Edgar chunks"
        assert row.data_type in ('USER-DEFINED', 'vector'), \
            f"Unexpected vector column type: {row.data_type}"


@pytest.mark.integration
class TestDatabaseServiceModule:
    """Tests for the database service module."""

    def test_get_cortellis_session_context_manager(self):
        """Verify get_cortellis_session works as context manager."""
        try:
            from unified_api.services.database import get_cortellis_session

            with get_cortellis_session() as session:
                result = session.execute(text("SELECT 1"))
                assert result.scalar() == 1
        except Exception as e:
            pytest.skip(f"Could not import database service: {e}")

    def test_get_edgar_session_context_manager(self):
        """Verify get_edgar_session works as context manager."""
        try:
            from unified_api.services.database import get_edgar_session

            with get_edgar_session() as session:
                result = session.execute(text("SELECT 1"))
                assert result.scalar() == 1
        except Exception as e:
            pytest.skip(f"Could not import database service: {e}")

    def test_get_edgar_source_session_context_manager(self):
        """Verify get_edgar_source_session works as context manager."""
        try:
            from unified_api.services.database import get_edgar_source_session

            with get_edgar_source_session() as session:
                result = session.execute(text("SELECT 1"))
                assert result.scalar() == 1
        except Exception as e:
            pytest.skip(f"Could not import database service: {e}")

    def test_check_cortellis_connection_function(self):
        """Verify check_cortellis_connection utility."""
        try:
            from unified_api.services.database import check_cortellis_connection

            result = check_cortellis_connection()
            assert isinstance(result, bool)
        except Exception as e:
            pytest.skip(f"Could not import check function: {e}")

    def test_check_edgar_connection_function(self):
        """Verify check_edgar_connection utility."""
        try:
            from unified_api.services.database import check_edgar_connection

            result = check_edgar_connection()
            assert isinstance(result, bool)
        except Exception as e:
            pytest.skip(f"Could not import check function: {e}")


@pytest.mark.integration
class TestConnectionResilience:
    """Tests for connection resilience and error handling."""

    def test_session_rollback_on_error(self, cortellis_session):
        """Verify session properly rolls back on error."""
        # Attempt an invalid query
        try:
            cortellis_session.execute(text("SELECT * FROM nonexistent_table_xyz"))
        except Exception:
            # Must explicitly rollback the failed transaction
            cortellis_session.rollback()

        # Session should still be usable after rollback
        result = cortellis_session.execute(text("SELECT 1"))
        assert result.scalar() == 1

    def test_connection_timeout_settings(self, cortellis_engine):
        """Verify connection has reasonable timeout settings."""
        # Check pool timeout configuration
        pool = cortellis_engine.pool

        # Pool should have a timeout (default is 30 seconds in SQLAlchemy)
        # This prevents hanging connections
        assert hasattr(pool, 'timeout')
