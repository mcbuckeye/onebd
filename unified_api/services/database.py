"""
Database connection management for unified platform

Manages connections to:
- Cortellis PostgreSQL (145K+ deals, 52K companies)
- Edgar Source PostgreSQL (314K SEC filings, 3.3M embedded chunks)

Note: In the consolidated setup, there is only ONE Edgar database
(edgar-source-db) that contains all SEC filings and embedded chunks.
The legacy edgar_db_url and edgar_source_db_url both point to this
same database for backwards compatibility.
"""
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool
import structlog

from unified_api.config import settings

logger = structlog.get_logger(__name__)


# Cortellis database engine (deals, companies, contracts)
_cortellis_engine = None
_cortellis_session_factory = None

# Edgar source database engine (SEC filings, chunks with embeddings)
# In consolidated setup, this is the ONLY Edgar database
_edgar_source_engine = None
_edgar_source_session_factory = None


def get_cortellis_engine():
    """Get or create the Cortellis database engine"""
    global _cortellis_engine

    if _cortellis_engine is None:
        _cortellis_engine = create_engine(
            settings.cortellis_db_url,
            poolclass=QueuePool,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout_seconds,
            pool_recycle=1800,  # Recycle connections every 30 min
            pool_pre_ping=True,  # Verify connections before use
            echo=settings.debug,
        )
        logger.info("Cortellis database engine created")

    return _cortellis_engine


def get_edgar_engine():
    """Get or create the Edgar database engine.

    Note: In consolidated setup, this returns the same engine as
    get_edgar_source_engine() since both point to the same database.
    """
    # Use the source engine since they're the same database now
    return get_edgar_source_engine()


def get_cortellis_session_factory():
    """Get or create the Cortellis session factory"""
    global _cortellis_session_factory

    if _cortellis_session_factory is None:
        engine = get_cortellis_engine()
        _cortellis_session_factory = sessionmaker(
            bind=engine,
            autocommit=False,
            autoflush=False,
        )

    return _cortellis_session_factory


def get_edgar_session_factory():
    """Get or create the Edgar session factory.

    Note: In consolidated setup, this returns the same factory as
    get_edgar_source_session_factory() since both use the same database.
    """
    # Use the source session factory since they're the same database now
    return get_edgar_source_session_factory()


def get_edgar_source_engine():
    """Get or create the Edgar source database engine (for chunk search)"""
    global _edgar_source_engine

    if _edgar_source_engine is None:
        _edgar_source_engine = create_engine(
            settings.edgar_source_db_url,
            poolclass=QueuePool,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout_seconds,
            pool_recycle=1800,  # Recycle connections every 30 min
            pool_pre_ping=True,  # Verify connections before use
            echo=settings.debug,
        )
        logger.info("Edgar source database engine created")

    return _edgar_source_engine


def get_edgar_source_session_factory():
    """Get or create the Edgar source session factory"""
    global _edgar_source_session_factory

    if _edgar_source_session_factory is None:
        engine = get_edgar_source_engine()
        _edgar_source_session_factory = sessionmaker(
            bind=engine,
            autocommit=False,
            autoflush=False,
        )

    return _edgar_source_session_factory


@contextmanager
def get_cortellis_session() -> Generator[Session, None, None]:
    """Get a Cortellis database session"""
    factory = get_cortellis_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def get_edgar_session() -> Generator[Session, None, None]:
    """Get an Edgar database session"""
    factory = get_edgar_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def get_edgar_source_session() -> Generator[Session, None, None]:
    """Get an Edgar source database session (for chunk search)"""
    factory = get_edgar_source_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_cortellis_connection() -> bool:
    """Check if Cortellis database is reachable"""
    try:
        engine = get_cortellis_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error("Cortellis database connection failed", error=str(e))
        return False


def check_edgar_connection() -> bool:
    """Check if Edgar database is reachable"""
    try:
        engine = get_edgar_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error("Edgar database connection failed", error=str(e))
        return False


def close_all_connections():
    """Close all database connections"""
    global _cortellis_engine, _edgar_source_engine
    global _cortellis_session_factory, _edgar_source_session_factory

    if _cortellis_engine:
        _cortellis_engine.dispose()
        _cortellis_engine = None
        logger.info("Cortellis database connections closed")

    if _edgar_source_engine:
        _edgar_source_engine.dispose()
        _edgar_source_engine = None
        logger.info("Edgar source database connections closed")
    _cortellis_session_factory = None
    _edgar_source_session_factory = None
