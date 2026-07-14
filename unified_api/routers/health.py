"""
Health check endpoints for monitoring.
"""
from fastapi import APIRouter
from pydantic import BaseModel
import structlog
import redis
from datetime import date, datetime, timedelta, timezone
import math
from pathlib import Path
import re

from unified_api.config import settings
from unified_api.services.database import check_cortellis_connection, check_edgar_connection

logger = structlog.get_logger(__name__)

router = APIRouter()


def _build_commit() -> str:
    """Return immutable image commit metadata when built from a Git checkout."""
    try:
        commit = Path("/app/BUILD_COMMIT").read_text().strip()
    except OSError:
        return "unknown"
    return commit if re.fullmatch(r"[0-9a-f]{40}", commit) else "unknown"


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
    if run_status == "running" and completed is None:
        return {
            "status": "running",
            "age_hours": None,
            "detail": "run in progress; no prior completion timestamp",
        }
    if completed is None:
        return {"status": "critical", "age_hours": None, "detail": "no completed run"}

    age_hours = round(
        (datetime.now(timezone.utc) - completed).total_seconds() / 3600,
        1,
    )
    if run_status == "failed":
        status = "critical"
    elif run_status == "partial":
        status = "warning"
    elif run_status == "running":
        status = "running"
    elif age_hours >= critical_hours:
        status = "critical"
    elif age_hours >= warn_hours:
        status = "warning"
    else:
        status = "ok"
    detail = f"last completed {age_hours:.1f}h ago"
    if run_status in {"failed", "partial"}:
        detail = f"last run {run_status}; {detail}"
    return {
        "status": status,
        "age_hours": age_hours,
        "detail": detail,
    }


def _as_date(value):
    if value is None:
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _backfill_progress(
    cursor,
    target,
    runs,
    *,
    schedule_interval_hours=2.0,
    fallback_days_per_run=7.0,
):
    """Estimate EDGAR catch-up from append-only observed run history."""
    cursor = _as_date(cursor)
    target = _as_date(target)
    if cursor is None or target is None:
        return {
            "backlog_days": None,
            "estimate_status": "unavailable",
            "detail": "cursor or target is unavailable",
        }

    backlog_days = max(0, (target - cursor).days)
    completed_runs = []
    total_days_advanced = 0
    total_filings = 0
    total_duration_hours = 0.0
    for run in runs or []:
        if run.get("status") not in {"completed", "partial"}:
            continue
        start = _as_date(run.get("cursor_start"))
        end = _as_date(run.get("cursor_end"))
        started_at = _as_utc(run.get("started_at"))
        completed_at = _as_utc(run.get("completed_at"))
        if start is None or end is None or completed_at is None or started_at is None:
            continue
        duration_hours = max(
            0.0,
            (completed_at - started_at).total_seconds() / 3600,
        )
        completed_runs.append(run)
        total_days_advanced += max(0, (end - start).days)
        total_filings += int(run.get("filings_fetched") or 0)
        total_duration_hours += duration_hours

    if completed_runs and total_days_advanced > 0:
        days_per_run = total_days_advanced / len(completed_runs)
        estimate_basis = "observed"
    else:
        days_per_run = max(0.1, float(fallback_days_per_run))
        estimate_basis = "configured_capacity"

    average_duration_hours = (
        total_duration_hours / len(completed_runs) if completed_runs else None
    )
    effective_interval = max(
        float(schedule_interval_hours),
        average_duration_hours or 0.0,
    )
    estimated_runs = math.ceil(backlog_days / days_per_run) if backlog_days else 0
    estimated_hours = round(estimated_runs * effective_interval, 1)
    estimated_completion = datetime.now(timezone.utc) + timedelta(hours=estimated_hours)

    return {
        "backlog_days": backlog_days,
        "target_date": target.isoformat(),
        "cursor_date": cursor.isoformat(),
        "runs_sampled": len(completed_runs),
        "cursor_days_per_run": round(days_per_run, 2),
        "average_run_duration_seconds": (
            round(average_duration_hours * 3600, 1)
            if average_duration_hours is not None
            else None
        ),
        "filings_per_run": (
            round(total_filings / len(completed_runs), 2)
            if completed_runs
            else None
        ),
        "filings_per_hour": (
            round(total_filings / total_duration_hours, 2)
            if total_duration_hours > 0
            else None
        ),
        "estimated_runs_remaining": estimated_runs,
        "estimated_catchup_hours": estimated_hours,
        "estimated_completion_at": estimated_completion.isoformat(),
        "estimate_status": "caught_up" if backlog_days == 0 else estimate_basis,
    }


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    version: str
    commit: str
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
        commit=_build_commit(),
        services=services,
    )


@router.get("/api/health")
async def api_health():
    """Simple health check for load balancers."""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "commit": _build_commit(),
    }


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
                    last_success = session.execute(text(
                        "SELECT MAX(completed_at) FROM sync_log WHERE status = 'completed'"
                    )).scalar()
                    sync_info["last_success_at"] = last_success
                    sync_info["freshness"] = _sync_freshness(
                        last_success,
                        settings.cortellis_freshness_warn_hours,
                        settings.cortellis_freshness_critical_hours,
                        last_sync["status"],
                    )
                    sync_info["latest_local_change"] = session.execute(text(
                        "SELECT MAX(date_change_last) FROM deals"
                    )).scalar()
                    sources["cortellis_sync"] = sync_info
                    sources["last_sync_time"] = last_success
            except Exception:
                pass

            # Common operational state includes advisory retry timing and the
            # last alert transition for every instrumented source job.
            if session.execute(text(
                "SELECT to_regclass('public.source_job_state')"
            )).scalar():
                from unified_api.services.source_monitoring import read_source_job_states

                sources["source_jobs"] = read_source_job_states(session)
                sources["source_job_notifications"] = [
                    dict(row) for row in session.execute(text("""
                        SELECT id, source_key, event_type, severity, detail,
                               created_at, delivered_at, delivery_error
                        FROM source_job_notifications
                        ORDER BY created_at DESC
                        LIMIT 20
                    """)).mappings().all()
                ]
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
                    history = []
                    if session.execute(text(
                        "SELECT to_regclass('public.edgar_sync_runs')"
                    )).scalar():
                        history = session.execute(text("""
                            SELECT cursor_start, cursor_end, started_at, completed_at,
                                   status, filings_fetched
                            FROM edgar_sync_runs
                            WHERE lane = 'backfill'
                            ORDER BY completed_at DESC
                            LIMIT 30
                        """)).mappings().all()
                    progress = _backfill_progress(
                        cursor,
                        datetime.now(timezone.utc).date() - date.resolution,
                        history,
                        schedule_interval_hours=2,
                        fallback_days_per_run=settings.edgar_sync_batch_days,
                    )
                    backfill_info["backlog_days"] = progress["backlog_days"]
                    backfill_info["progress"] = progress
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
    common_states = {
        state["source_key"]: state
        for state in sources.get("source_jobs", [])
    }
    for source_name, source_key, label in (
        ("cortellis_sync", "cortellis", "Cortellis Sync"),
        ("edgar_recent_sync", "edgar_recent", "EDGAR Recent Sync"),
        ("edgar_backfill_sync", "edgar_backfill", "EDGAR Backfill Sync"),
    ):
        common_state = common_states.get(source_key)
        if common_state:
            from unified_api.services.source_monitoring import (
                SOURCE_POLICIES,
                classify_source_job,
            )

            severity, detail = classify_source_job(
                common_state, SOURCE_POLICIES[source_key]
            )
            sync_checks.append({
                "name": label,
                "status": severity,
                "detail": detail,
            })
            continue
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

    graph_state = common_states.get("neo4j")
    if graph_state:
        from unified_api.services.source_monitoring import (
            SOURCE_POLICIES,
            classify_source_job,
        )

        severity, detail = classify_source_job(
            graph_state, SOURCE_POLICIES["neo4j"]
        )
        sync_checks.append({
            "name": "Neo4j Graph Sync",
            "status": severity,
            "detail": detail,
        })

    catalog_state = common_states.get("cortellis_catalog")
    if catalog_state:
        from unified_api.services.source_monitoring import (
            SOURCE_POLICIES,
            classify_source_job,
        )

        severity, detail = classify_source_job(
            catalog_state, SOURCE_POLICIES["cortellis_catalog"]
        )
        sync_checks.append({
            "name": "Cortellis Catalog Reconciliation",
            "status": severity,
            "detail": detail,
        })

    contract_state = common_states.get("cortellis_contracts")
    if contract_state:
        from unified_api.services.source_monitoring import (
            SOURCE_POLICIES,
            classify_source_job,
        )

        severity, detail = classify_source_job(
            contract_state, SOURCE_POLICIES["cortellis_contracts"]
        )
        sync_checks.append({
            "name": "Cortellis Contract Metadata Scan",
            "status": severity,
            "detail": detail,
        })

    deal_api_state = common_states.get("cortellis_deal_api")
    if deal_api_state:
        from unified_api.services.source_monitoring import (
            SOURCE_POLICIES,
            classify_source_job,
        )

        severity, detail = classify_source_job(
            deal_api_state, SOURCE_POLICIES["cortellis_deal_api"]
        )
        sync_checks.append({
            "name": "Cortellis Raw Response and Source Scan",
            "status": severity,
            "detail": detail,
        })

    for source_key, label in (
        ("clinicaltrials_recent", "ClinicalTrials.gov Recent Sync"),
        ("clinicaltrials_backfill", "ClinicalTrials.gov Historical Backfill"),
        ("chembl", "ChEMBL Exact Identifier Enrichment"),
        ("open_targets", "Open Targets Drug/Target Enrichment"),
    ):
        source_state = common_states.get(source_key)
        if not source_state:
            continue
        from unified_api.services.source_monitoring import (
            SOURCE_POLICIES,
            classify_source_job,
        )

        severity, detail = classify_source_job(
            source_state, SOURCE_POLICIES[source_key]
        )
        sync_checks.append({
            "name": label,
            "status": severity,
            "detail": detail,
        })

    health["checks"].extend(sync_checks)
    degraded = any(check["status"] in {"warning", "critical"} for check in sync_checks)

    return {
        "status": "degraded" if degraded else "healthy",
        "overall_score": health["overall_score"],
        "checks": health["checks"],
        "sources": sources,
    }
