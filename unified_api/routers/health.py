"""
Health check endpoints for monitoring.
"""
from fastapi import APIRouter
from pydantic import BaseModel
import structlog
import redis
from datetime import date, datetime, timezone

from unified_api.config import settings
from unified_api.services.database import check_cortellis_connection, check_edgar_connection

logger = structlog.get_logger(__name__)

router = APIRouter()


def _as_utc(value):
    """Normalize database timestamps for freshness calculations."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, datetime.min.time())
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sync_freshness(last_completed, warn_hours, critical_hours, run_status=None):
    """Return a consistent freshness status for a scheduled source job."""
    completed = _as_utc(last_completed)
    if completed is None:
        return {"status": "critical", "age_hours": None, "detail": "no completed run"}

    age_hours = round(
        (datetime.now(timezone.utc) - completed).total_seconds() / 3600,
        1,
    )
    if run_status == "failed":
        status = "critical"
    elif run_status == "running":
        status = "running"
    elif age_hours >= critical_hours:
        status = "critical"
    elif age_hours >= warn_hours:
        status = "warning"
    else:
        status = "ok"
    return {
        "status": status,
        "age_hours": age_hours,
        "detail": f"last completed {age_hours:.1f}h ago",
    }


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
    cortellis_embedded = 0
    cortellis_fulltext = 0
    try:
        with get_cortellis_session() as session:
            # Count contracts with text content
            result = session.execute(text(
                "SELECT COUNT(*) FROM deal_contracts WHERE has_text = true"
            ))
            cortellis_contracts = result.scalar() or 0

            # Count chunks
            result = session.execute(text("""
                SELECT COUNT(*) AS total, COUNT(embedding) AS embedded
                FROM contract_chunks
            """)).fetchone()
            cortellis_chunks = result.total or 0
            cortellis_embedded = result.embedded or 0

            cortellis_fulltext = session.execute(text(
                "SELECT COUNT(*) FROM contract_content WHERE content_tsvector IS NOT NULL"
            )).scalar() or 0
    except Exception as e:
        logger.warning("Failed to get Cortellis stats", error=str(e))

    # Get Edgar stats
    edgar_chunks = 0
    edgar_embedded = 0
    try:
        with get_edgar_source_session() as session:
            result = session.execute(text("""
                SELECT COUNT(*) AS total, COUNT(vector) AS embedded
                FROM chunks
            """)).fetchone()
            edgar_chunks = result.total or 0
            edgar_embedded = result.embedded or 0
    except Exception as e:
        logger.warning("Failed to get Edgar stats", error=str(e))

    total_chunks = cortellis_chunks + edgar_chunks
    embedded_chunks = cortellis_embedded + edgar_embedded

    return IndexStatus(
        total_text_contracts=cortellis_contracts,
        indexed_for_fulltext=cortellis_fulltext,
        total_chunks=total_chunks,
        embedded_chunks=embedded_chunks,
        fulltext_pct=(cortellis_fulltext / cortellis_contracts * 100) if cortellis_contracts else 0.0,
        embedding_pct=(embedded_chunks / total_chunks * 100) if total_chunks else 0.0,
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

            # Get actual last sync and source-watermark information.
            try:
                last_sync = session.execute(text("""
                    SELECT status, started_at, completed_at, records_processed,
                           records_created, records_updated, contracts_downloaded,
                           error_message
                    FROM sync_log
                    ORDER BY started_at DESC
                    LIMIT 1
                """)).mappings().first()
                if last_sync:
                    sync_info = dict(last_sync)
                    sync_info["freshness"] = _sync_freshness(
                        last_sync["completed_at"],
                        settings.cortellis_freshness_warn_hours,
                        settings.cortellis_freshness_critical_hours,
                        last_sync["status"],
                    )
                    sync_info["latest_local_change"] = session.execute(text(
                        "SELECT MAX(date_change_last) FROM deals"
                    )).scalar()
                    sources["cortellis_sync"] = sync_info
                    sources["last_sync_time"] = last_sync["completed_at"]
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

            if session.execute(text(
                "SELECT to_regclass('public.edgar_recent_sync_state')"
            )).scalar():
                recent = session.execute(text(
                    "SELECT * FROM edgar_recent_sync_state WHERE id = 1"
                )).mappings().first()
                if recent:
                    recent_info = dict(recent)
                    recent_info["freshness"] = _sync_freshness(
                        recent["completed_at"],
                        settings.edgar_freshness_warn_hours,
                        settings.edgar_freshness_critical_hours,
                        recent["status"],
                    )
                    sources["edgar_recent_sync"] = recent_info

            if session.execute(text(
                "SELECT to_regclass('public.edgar_sync_state')"
            )).scalar():
                backfill = session.execute(text(
                    "SELECT * FROM edgar_sync_state WHERE id = 1"
                )).mappings().first()
                if backfill:
                    backfill_info = dict(backfill)
                    cursor = backfill["last_index_date"]
                    backfill_info["backlog_days"] = max(
                        0,
                        ((datetime.now(timezone.utc).date() - date.resolution) - cursor).days,
                    )
                    backfill_info["freshness"] = _sync_freshness(
                        backfill.get("completed_at") or backfill.get("last_run_at"),
                        settings.edgar_freshness_warn_hours,
                        settings.edgar_freshness_critical_hours,
                        backfill["status"],
                    )
                    sources["edgar_backfill_sync"] = backfill_info
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

    sync_checks = []
    for source_name, label in (
        ("cortellis_sync", "Cortellis Sync"),
        ("edgar_recent_sync", "EDGAR Recent Sync"),
        ("edgar_backfill_sync", "EDGAR Backfill Sync"),
    ):
        source = sources.get(source_name)
        if source:
            freshness = source.get("freshness", {})
            sync_checks.append({
                "name": label,
                "status": freshness.get("status", "critical"),
                "detail": freshness.get("detail", "freshness unavailable"),
            })
        else:
            sync_checks.append({
                "name": label,
                "status": "critical",
                "detail": "sync state unavailable",
            })

    health["checks"].extend(sync_checks)
    degraded = any(check["status"] in {"warning", "critical"} for check in sync_checks)

    return {
        "status": "degraded" if degraded else "healthy",
        "overall_score": health["overall_score"],
        "checks": health["checks"],
        "sources": sources,
    }
