"""
BD Intelligence Platform - Test Configuration and Fixtures

Provides pytest fixtures for:
- Database connections (Cortellis, Edgar, Neo4j)
- Mock data generators
- API test client
- Cleanup utilities
"""
import os
import sys
from pathlib import Path

# Add parent directory to path for unified_api imports
# Add project root to path for unified_api imports
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest
from typing import Generator, Dict, Any, Optional
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

# Set test environment before importing app modules
os.environ.setdefault("TESTING", "true")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# Import after environment setup
from fastapi.testclient import TestClient


# =============================================================================
# Configuration
# =============================================================================

class TestConfig:
    """Test configuration settings."""

    # Use same environment variables as the app, with test-specific overrides
    # Priority: TEST_*_URL env var > App's *_URL env var > fallback defaults

    # Cortellis DB - use app's env var if available
    CORTELLIS_DB_URL = os.environ.get(
        "TEST_CORTELLIS_DB_URL",
        os.environ.get("CORTELLIS_DB_URL", "postgresql://cortellis:changeme@localhost:5433/cortellis")
    )

    # Edgar Source DB (SEC filings, 3.3M chunks with embeddings)
    # In consolidated setup, this is the ONLY Edgar database (port 5432)
    # The old bd-edgar-db (port 5434) has been removed
    EDGAR_SOURCE_DB_URL = os.environ.get(
        "TEST_EDGAR_SOURCE_DB_URL",
        os.environ.get("EDGAR_SOURCE_DB_URL",
            os.environ.get("EDGAR_DB_URL", "postgresql://postgres:postgres@localhost:5432/deals"))
    )

    # Legacy alias for compatibility
    EDGAR_DB_URL = EDGAR_SOURCE_DB_URL

    # Neo4j
    NEO4J_URI = os.environ.get(
        "TEST_NEO4J_URI",
        os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    )
    NEO4J_USER = os.environ.get(
        "TEST_NEO4J_USER",
        os.environ.get("NEO4J_USER", "neo4j")
    )
    NEO4J_PASSWORD = os.environ.get(
        "TEST_NEO4J_PASSWORD",
        os.environ.get("NEO4J_PASSWORD", "bdplatform123")
    )

    # Skip flags for CI environments without full stack
    SKIP_CORTELLIS = os.environ.get("SKIP_CORTELLIS_TESTS", "false").lower() == "true"
    SKIP_EDGAR = os.environ.get("SKIP_EDGAR_TESTS", "false").lower() == "true"
    SKIP_NEO4J = os.environ.get("SKIP_NEO4J_TESTS", "false").lower() == "true"


# =============================================================================
# Database Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def cortellis_engine():
    """Create Cortellis database engine for entire test session."""
    if TestConfig.SKIP_CORTELLIS:
        pytest.skip("Cortellis tests disabled")

    try:
        engine = create_engine(
            TestConfig.CORTELLIS_DB_URL,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=5,
        )
        # Verify connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        yield engine
        engine.dispose()
    except Exception as e:
        pytest.skip(f"Could not connect to Cortellis DB: {e}")


@pytest.fixture(scope="session")
def edgar_engine():
    """Create Edgar database engine for entire test session.

    Note: In the consolidated setup, there is only ONE Edgar database
    (edgar-source-db on port 5432) containing all 314K SEC filings
    and 3.3M embedded chunks.
    """
    if TestConfig.SKIP_EDGAR:
        pytest.skip("Edgar tests disabled")

    try:
        engine = create_engine(
            TestConfig.EDGAR_SOURCE_DB_URL,
            pool_pre_ping=True,
            pool_size=2,
            max_overflow=5,
        )
        # Verify connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        yield engine
        engine.dispose()
    except Exception as e:
        pytest.skip(f"Could not connect to Edgar DB: {e}")


@pytest.fixture(scope="session")
def edgar_source_engine(edgar_engine):
    """Create Edgar source database engine (for chunk searches).

    Note: In the consolidated setup, edgar_engine and edgar_source_engine
    are the SAME database. This fixture exists for backwards compatibility.
    """
    # In consolidated setup, they're the same engine
    yield edgar_engine


@pytest.fixture
def cortellis_session(cortellis_engine) -> Generator[Session, None, None]:
    """Provide a transactional Cortellis database session."""
    SessionLocal = sessionmaker(bind=cortellis_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def edgar_session(edgar_engine) -> Generator[Session, None, None]:
    """Provide a transactional Edgar database session."""
    SessionLocal = sessionmaker(bind=edgar_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def edgar_source_session(edgar_source_engine) -> Generator[Session, None, None]:
    """Provide a transactional Edgar source database session."""
    SessionLocal = sessionmaker(bind=edgar_source_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# =============================================================================
# Neo4j Fixtures
# =============================================================================

@pytest.fixture(scope="session")
def neo4j_driver():
    """Create Neo4j driver for entire test session."""
    if TestConfig.SKIP_NEO4J:
        pytest.skip("Neo4j tests disabled")

    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            TestConfig.NEO4J_URI,
            auth=(TestConfig.NEO4J_USER, TestConfig.NEO4J_PASSWORD),
        )
        # Verify connection
        driver.verify_connectivity()
        yield driver
        driver.close()
    except Exception as e:
        pytest.skip(f"Could not connect to Neo4j: {e}")


@pytest.fixture
def neo4j_session(neo4j_driver):
    """Provide a Neo4j session."""
    session = neo4j_driver.session()
    try:
        yield session
    finally:
        session.close()


# =============================================================================
# API Test Client
# =============================================================================

@pytest.fixture(scope="module")
def api_client():
    """Create FastAPI test client."""
    # Import here to avoid import errors if app has issues
    from unified_api.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def mock_cortellis_session():
    """Mock Cortellis session for unit tests without DB."""
    with patch("unified_api.services.database.get_cortellis_session") as mock:
        session = MagicMock(spec=Session)
        mock.return_value.__enter__ = MagicMock(return_value=session)
        mock.return_value.__exit__ = MagicMock(return_value=False)
        yield session


@pytest.fixture
def mock_edgar_session():
    """Mock Edgar session for unit tests without DB."""
    with patch("unified_api.services.database.get_edgar_session") as mock:
        session = MagicMock(spec=Session)
        mock.return_value.__enter__ = MagicMock(return_value=session)
        mock.return_value.__exit__ = MagicMock(return_value=False)
        yield session


# =============================================================================
# Sample Data Fixtures
# =============================================================================

@pytest.fixture
def sample_deal_data() -> Dict[str, Any]:
    """Sample deal data for testing."""
    return {
        "id": 12345,
        "title": "Test License Agreement - ABBV / PFE",
        "deal_type": "License",
        "status": "Active",
        "date_start": "2024-01-15",
        "total_value": 500000000.0,
        "principal_company": "AbbVie Inc.",
        "partner_company": "Pfizer Inc.",
    }


@pytest.fixture
def sample_company_data() -> Dict[str, Any]:
    """Sample company data for testing."""
    return {
        "id": 100,
        "name": "AbbVie Inc.",
        "ticker": "ABBV",
        "company_type": "Large Pharma",
        "hq_country": "United States",
        "deal_count": 150,
    }


@pytest.fixture
def sample_edgar_company_data() -> Dict[str, Any]:
    """Sample Edgar company data for testing."""
    return {
        "id": 50,
        "name": "AbbVie Inc.",
        "cik": "0001551152",
        "ticker": "ABBV",
        "sic_code": "2834",
        "filing_count": 245,
    }


@pytest.fixture
def sample_contract_chunk() -> Dict[str, Any]:
    """Sample contract chunk for search testing."""
    return {
        "chunk_id": 99999,
        "deal_id": 12345,
        "contract_id": 500,
        "content": "The royalty rate shall be 8% of Net Sales for Licensed Products in the Territory.",
        "score": 0.85,
    }


@pytest.fixture
def sample_xref_data() -> Dict[str, Any]:
    """Sample company cross-reference data."""
    return {
        "cortellis_id": 100,
        "edgar_company_id": 50,
        "cik": "0001551152",
        "ticker": "ABBV",
        "canonical_name": "AbbVie Inc.",
        "match_method": "exact_ticker",
        "match_confidence": 1.0,
    }


# =============================================================================
# Utility Functions
# =============================================================================

def get_table_count(session: Session, table_name: str) -> int:
    """Get row count for a table."""
    result = session.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
    return result.scalar()


def table_exists(session: Session, table_name: str) -> bool:
    """Check if a table exists."""
    result = session.execute(text("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = :table_name
        )
    """), {"table_name": table_name})
    return result.scalar()


def index_exists(session: Session, index_name: str) -> bool:
    """Check if an index exists."""
    result = session.execute(text("""
        SELECT EXISTS (
            SELECT FROM pg_indexes
            WHERE indexname = :index_name
        )
    """), {"index_name": index_name})
    return result.scalar()


# =============================================================================
# Markers
# =============================================================================

def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")
    config.addinivalue_line("markers", "cortellis: marks tests requiring Cortellis DB")
    config.addinivalue_line("markers", "edgar: marks tests requiring Edgar DB")
    config.addinivalue_line("markers", "neo4j: marks tests requiring Neo4j")
