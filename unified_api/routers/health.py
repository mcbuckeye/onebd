"""
Health check endpoints for monitoring.
"""
from fastapi import APIRouter
from pydantic import BaseModel
import structlog
import redis

from unified_api.config import settings
from unified_api.services.database import check_cortellis_connection, check_edgar_connection

logger = structlog.get_logger(__name__)

router = APIRouter()


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    services: dict


class IndexStatus(BaseModel):
    """Index status for RAG search."""
    total_text_contracts: int
    indexed_for_fulltext: int
    total_chunks: int
    embedded_chunks: int
    fulltext_pct: float
    embedding_pct: float


def check_redis_connection() -> bool:
    """Check if Redis is reachable"""
    try:
        r = redis.from_url(settings.redis_url)
        r.ping()
        return True
    except Exception as e:
        logger.error("Redis connection failed", error=str(e))
        return False


def check_neo4j_connection() -> bool:
    """Check if Neo4j is reachable"""
    try:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password)
        )
        with driver.session() as session:
            session.run("RETURN 1")
        driver.close()
        return True
    except Exception as e:
        logger.error("Neo4j connection failed", error=str(e))
        return False


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Check health of all services.

    Returns status of:
    - Cortellis PostgreSQL
    - Edgar PostgreSQL
    - Neo4j Graph Database
    - Redis
    """
    services = {}

    # Check each service
    services["cortellis_db"] = "healthy" if check_cortellis_connection() else "unhealthy"
    services["edgar_db"] = "healthy" if check_edgar_connection() else "unhealthy"
    services["neo4j"] = "healthy" if check_neo4j_connection() else "unhealthy"
    services["redis"] = "healthy" if check_redis_connection() else "unhealthy"

    # Overall status
    all_healthy = all(s == "healthy" for s in services.values())

    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        version=settings.app_version,
        services=services,
    )


@router.get("/api/health")
async def api_health():
    """Simple health check for load balancers."""
    return {"status": "healthy"}


@router.get("/api/index-status", response_model=IndexStatus)
async def index_status():
    """
    Get indexing status for RAG search.

    Returns counts and percentages for:
    - Full-text indexed contracts (Cortellis)
    - Embedded chunks for semantic search (both sources)
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session, get_edgar_source_session

    # Get Cortellis contract stats
    cortellis_contracts = 0
    cortellis_chunks = 0
    try:
        with get_cortellis_session() as session:
            # Count contracts with text content
            result = session.execute(text(
                "SELECT COUNT(*) FROM deal_contracts WHERE has_text = true"
            ))
            cortellis_contracts = result.scalar() or 0

            # Count chunks
            result = session.execute(text("SELECT COUNT(*) FROM contract_chunks"))
            cortellis_chunks = result.scalar() or 0
    except Exception as e:
        logger.warning("Failed to get Cortellis stats", error=str(e))

    # Get Edgar stats
    edgar_chunks = 0
    try:
        with get_edgar_source_session() as session:
            result = session.execute(text("SELECT COUNT(*) FROM chunks"))
            edgar_chunks = result.scalar() or 0
    except Exception as e:
        logger.warning("Failed to get Edgar stats", error=str(e))

    total_chunks = cortellis_chunks + edgar_chunks
    embedded_chunks = total_chunks  # All chunks are embedded

    return IndexStatus(
        total_text_contracts=cortellis_contracts,
        indexed_for_fulltext=cortellis_contracts,  # All have fulltext
        total_chunks=total_chunks,
        embedded_chunks=embedded_chunks,
        fulltext_pct=100.0 if cortellis_contracts > 0 else 0.0,
        embedding_pct=100.0 if total_chunks > 0 else 0.0,
    )


@router.get("/api/health/data")
async def data_health_check():
    """
    Comprehensive data health check across all sources.
    Reports on: Cortellis PG, EDGAR PG, Neo4j graph, sync freshness.
    """
    from unified_api.services.database import get_cortellis_session, get_edgar_source_session
    from unified_api.services.data_health import compute_health_score
    from sqlalchemy import text

    sources = {}

    # Cortellis DB metrics
    try:
        with get_cortellis_session() as session:
            counts = session.execute(text("""
                SELECT
                    (SELECT COUNT(*) FROM deals) as deals_total,
                    (SELECT COUNT(*) FROM deal_finance_summary
                     WHERE total_projected_current_amount IS NOT NULL) as deals_with_financials,
                    (SELECT COUNT(*) FROM companies) as companies_total,
                    (SELECT COUNT(*) FROM company_xref) as companies_with_xref,
                    (SELECT MAX(date_start)::text FROM deals) as latest_deal_date
            """)).fetchone()

            sources["cortellis_deals"] = {
                "total": counts.deals_total,
                "with_financials": counts.deals_with_financials,
                "disclosure_rate": f"{(counts.deals_with_financials / counts.deals_total * 100):.1f}%" if counts.deals_total > 0 else "N/A",
                "latest_deal": counts.latest_deal_date,
            }
            sources["companies"] = {
                "total": counts.companies_total,
                "cross_referenced": counts.companies_with_xref,
            }

            # Get actual last sync time from sync_log
            try:
                last_sync = session.execute(text(
                    "SELECT MAX(completed_at)::text FROM sync_log WHERE status = 'completed'"
                )).scalar()
                if last_sync:
                    sources["last_sync_time"] = last_sync
            except Exception:
                pass
    except Exception as e:
        sources["cortellis_deals"] = {"error": str(e)}
        sources["companies"] = {"error": str(e)}

    # EDGAR DB metrics
    try:
        with get_edgar_source_session() as session:
            edgar = session.execute(text("""
                SELECT
                    (SELECT COUNT(*) FROM documents) as filings_total,
                    (SELECT COUNT(*) FROM chunks) as chunks_total,
                    (SELECT MAX(published_at)::text FROM documents) as latest_filing
            """)).fetchone()

            sources["edgar"] = {
                "filings": edgar.filings_total,
                "chunks": edgar.chunks_total,
                "latest_filing": edgar.latest_filing,
            }
    except Exception as e:
        sources["edgar"] = {"error": str(e)}

    # Neo4j metrics
    graph_companies = 0
    graph_deals = 0
    graph_rels = 0
    try:
        from unified_api.services.graph_sync import get_graph_sync_service
        graph_service = get_graph_sync_service()
        stats = graph_service.get_sync_stats()
        graph_companies = stats.get("nodes", {}).get("Company", 0)
        graph_deals = stats.get("nodes", {}).get("Deal", 0)
        graph_rels = sum(stats.get("relationships", {}).values())
        sources["neo4j"] = {
            "companies": graph_companies,
            "deals": graph_deals,
            "relationships": graph_rels,
            "node_types": stats.get("nodes", {}),
            "relationship_types": stats.get("relationships", {}),
        }
    except Exception as e:
        sources["neo4j"] = {"error": str(e)}

    # Redis metrics
    try:
        r = redis.from_url(settings.redis_url)
        redis_info = r.info("memory")
        cache_keys = r.dbsize()
        sources["redis"] = {
            "cache_keys": cache_keys,
            "memory_used": redis_info.get("used_memory_human", "unknown"),
        }
    except Exception as e:
        sources["redis"] = {"error": str(e)}

    # Compute health score
    metrics = {
        "deals_total": sources.get("cortellis_deals", {}).get("total", 0),
        "deals_with_financials": sources.get("cortellis_deals", {}).get("with_financials", 0),
        "companies_total": sources.get("companies", {}).get("total", 0),
        "companies_with_xref": sources.get("companies", {}).get("cross_referenced", 0),
        "graph_companies": graph_companies,
        "graph_deals": graph_deals,
        "graph_relationships": graph_rels,
        "last_sync": sources.get("last_sync_time", sources.get("cortellis_deals", {}).get("latest_deal", None)),
    }

    health = compute_health_score(metrics)

    return {
        "overall_score": health["overall_score"],
        "checks": health["checks"],
        "sources": sources,
    }
