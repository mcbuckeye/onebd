"""
Celery application configuration and task definitions.
"""
from celery import Celery
from celery.schedules import crontab
import structlog

from unified_api.config import settings

logger = structlog.get_logger(__name__)

# Create Celery app
celery_app = Celery(
    "bd_intelligence",
    broker=settings.broker_url,
    backend=settings.result_backend,
)

# Configure Celery
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # Task routing - different queues for different task types
    task_routes={
        # Rate-limited SEC EDGAR tasks go to dedicated queue
        "unified_api.workers.tasks.edgar.*": {"queue": "edgar"},
        # Graph sync tasks
        "unified_api.workers.tasks.graph.*": {"queue": "graph"},
        # Everything else goes to default queue
        "*": {"queue": "celery"},
    },

    # Beat schedule for periodic tasks
    beat_schedule={
        # Always fetch current SEC filings daily, independent of backfill.
        "fetch-edgar-filings": {
            "task": "unified_api.workers.tasks.edgar.fetch_new_filings",
            "schedule": crontab(hour=2, minute=0),
        },
        # Maintain the caught-up historical cursor every two hours. Each run is
        # bounded and the EDGAR queue has concurrency=1, so runs cannot issue
        # concurrent SEC requests.
        "backfill-edgar-filings": {
            "task": "unified_api.workers.tasks.edgar.backfill_filings",
            "schedule": crontab(hour="*/2", minute=15),
        },
        # Verify every CIK against the official SEC submissions identity record
        # before retaining its self-reported LEI/domain fields.
        "audit-sec-company-identities": {
            "task": "unified_api.workers.tasks.edgar.company_identities",
            "schedule": crontab(hour=3, minute=45),
        },
        # Current trial changes run after the documented weekday source refresh.
        "sync-clinicaltrials-recent": {
            "task": "unified_api.workers.tasks.clinicaltrials.recent",
            "schedule": crontab(hour=15, minute=30, day_of_week="1-5"),
        },
        # Advance the complete historical registry in bounded, resumable windows.
        "backfill-clinicaltrials": {
            "task": "unified_api.workers.tasks.clinicaltrials.backfill",
            "schedule": crontab(minute="7,22,37,52"),
        },
        # Sync Cortellis deals daily at 6:30 AM
        "sync-cortellis-deals": {
            "task": "unified_api.workers.tasks.cortellis.sync_deals",
            "schedule": crontab(hour=6, minute=30),
        },
        # Weekly full-ID reconciliation repairs historical omissions that a
        # date-watermarked incremental lane cannot see.
        "reconcile-cortellis-catalog": {
            "task": "unified_api.workers.tasks.cortellis.reconcile_catalog",
            "schedule": crontab(hour=4, minute=15, day_of_week="sunday"),
        },
        # Scan contract metadata independently in bounded, database-checkpointed
        # batches. API failures remain retryable and never become false negatives.
        "scan-cortellis-contract-metadata": {
            "task": "unified_api.workers.tasks.cortellis.scan_contract_metadata",
            "schedule": crontab(minute="*/10"),
        },
        # Preserve exact expanded responses and per-deal source citations in a
        # separate staggered lane so completeness survives worker restarts.
        "scan-cortellis-deal-api-coverage": {
            "task": "unified_api.workers.tasks.cortellis.scan_deal_api_coverage",
            "schedule": crontab(minute="5,15,25,35,45,55"),
        },
        # Sync graph database daily at 7:00 AM
        "sync-neo4j-graph": {
            "task": "unified_api.workers.tasks.graph.sync_all",
            "schedule": crontab(hour=7, minute=0),
        },
        # Auto-link deals to filings daily at 7:30 AM
        "link-deals-to-filings": {
            "task": "unified_api.workers.tasks.graph.link_deals_to_filings",
            "schedule": crontab(hour=7, minute=30),
        },
        # Check deal alerts daily at 8:00 AM
        "check-deal-alerts": {
            "task": "unified_api.workers.tasks.alerts.check_alerts",
            "schedule": crontab(hour=8, minute=0),
        },
        # Baseline-safe, per-user alerts for newly observed companies in a
        # tracked competitor's leading indication spaces.
        "check-company-entrant-alerts": {
            "task": "unified_api.workers.tasks.alerts.company_entrants",
            "schedule": crontab(hour=8, minute=15),
        },
        # Persist and notify only transitions (healthy -> warning/critical ->
        # recovered), so a stale source does not page operators repeatedly.
        "monitor-source-jobs": {
            "task": "unified_api.workers.tasks.monitoring.source_jobs",
            "schedule": crontab(minute="*/30"),
        },
        # Send daily deal digest at 7:00 AM EST (12:00 UTC)
        "daily-deal-digest": {
            "task": "unified_api.workers.tasks.digest.send_daily_digest",
            "schedule": crontab(hour=12, minute=0),  # 12:00 UTC = 7:00 AM EST
        },
        # Refresh materialized views daily at 8:30 AM (after syncs complete)
        "refresh-materialized-views": {
            "task": "unified_api.workers.tasks.maintenance.refresh_materialized_views",
            "schedule": crontab(hour=8, minute=30),
        },
        # Cheap, resumable normalization of the structured Cortellis finance JSON.
        "extract-cortellis-financial-terms": {
            "task": "unified_api.workers.tasks.enrichment.extract_financial_terms",
            "schedule": crontab(minute="*/15"),
        },
        # Deterministic, no-API-cost extraction of explicit financial clauses.
        "extract-contract-financial-clauses": {
            "task": (
                "unified_api.workers.tasks.enrichment."
                "extract_contract_financial_clauses"
            ),
            "schedule": crontab(minute="10,40"),
        },
        # Exact NCT citations create high-precision deal-to-trial links without
        # treating broad shared drug or disease names as deal-specific evidence.
        "extract-deal-clinical-trial-links": {
            "task": (
                "unified_api.workers.tasks.enrichment."
                "extract_deal_clinical_trial_links"
            ),
            "schedule": crontab(minute="8,28,48"),
        },
        # Per-alias PubChem enrichment stays below the official five-request/s
        # ceiling while advancing the corpus in bounded resumable batches.
        "enrich-pubchem-identifiers": {
            "task": "unified_api.workers.tasks.enrichment.pubchem_identifiers",
            "schedule": crontab(minute="*/2"),
        },
        # Exact structure mapping establishes durable ChEMBL identifiers.
        "enrich-chembl-identifiers": {
            "task": "unified_api.workers.tasks.enrichment.chembl_identifiers",
            "schedule": crontab(minute="1,5,9,13,17,21,25,29,33,37,41,45,49,53,57"),
        },
        # ChEMBL IDs then unlock batched Open Targets profiles and target links.
        "enrich-open-targets-profiles": {
            "task": "unified_api.workers.tasks.enrichment.open_targets_profiles",
            "schedule": crontab(minute="2,6,10,14,18,22,26,30,34,38,42,46,50,54,58"),
        },
        # Exact Swiss-Prot IDs from Open Targets unlock reviewed protein records.
        "enrich-uniprot-targets": {
            "task": "unified_api.workers.tasks.enrichment.uniprot_targets",
            "schedule": crontab(minute="3,7,11,15,19,23,27,31,35,39,43,47,51,55,59"),
        },
        # Structured UniProt/Ensembl citations become durable literature evidence.
        "enrich-europe-pmc-target-literature": {
            "task": "unified_api.workers.tasks.enrichment.europe_pmc_targets",
            "schedule": crontab(minute="0,4,8,12,16,20,24,28,32,36,40,44,48,52,56"),
        },
        # Batch pre-index contracts with PageIndex nightly at 3 AM
        "batch-pageindex-contracts": {
            "task": "unified_api.workers.tasks.pageindex.batch_index_contracts",
            "schedule": crontab(hour=3, minute=0),
        },
    },

    # Worker settings
    worker_prefetch_multiplier=1,  # Prevent workers from grabbing too many tasks
    task_acks_late=True,  # Acknowledge tasks after completion
    task_reject_on_worker_lost=True,  # Reject tasks if worker dies
)

# Auto-discover tasks from task modules
celery_app.autodiscover_tasks([
    "unified_api.workers.tasks",
])


# ============================================
# TASK DEFINITIONS
# ============================================


def _start_source_job(source_key: str) -> None:
    from unified_api.services.source_monitoring import record_source_job_started

    record_source_job_started(source_key)


def _finish_source_job(source_key: str, result: dict) -> dict:
    from unified_api.services.source_monitoring import record_source_job_finished

    record_source_job_finished(source_key, result)
    return result


def _cortellis_sync_service():
    """Build the legacy Deals API sync service from unified settings."""
    from src.config import AppConfig, CortellisConfig, DatabaseConfig, OpenAIConfig
    from src.sync import SyncService

    db_url = settings.cortellis_db_url
    return SyncService(AppConfig(
        cortellis=CortellisConfig(
            username=settings.cortellis_api_username,
            password=settings.cortellis_api_password,
            base_url=settings.cortellis_base_url,
        ),
        database=DatabaseConfig(
            host=db_url.split("@")[1].split(":")[0],
            port=int(db_url.split("@")[1].split(":")[1].split("/")[0]),
            database=db_url.split("/")[-1],
            user=db_url.split("://")[1].split(":")[0],
            password=db_url.split("://")[1].split(":")[1].split("@")[0],
        ),
        openai=OpenAIConfig(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        ),
        sync_schedule="",
        data_dir="/app/data",
        contracts_dir="/app/data/contracts",
    ))

@celery_app.task(name="unified_api.workers.tasks.edgar.fetch_new_filings")
def fetch_new_filings():
    """
    Fetch new SEC EDGAR filings.
    Runs on rate-limited edgar queue (1 worker, 10 req/sec).
    """
    logger.info("Starting EDGAR filing fetch")
    _start_source_job("edgar_recent")
    try:
        import asyncio
        from unified_api.services.edgar_ingestion import run_edgar_recent_sync

        result = asyncio.run(run_edgar_recent_sync())
        logger.info("EDGAR filing fetch complete", **result)
        return _finish_source_job("edgar_recent", result)
    except Exception as e:
        logger.error("EDGAR filing fetch failed", error=str(e))
        return _finish_source_job("edgar_recent", {"status": "failed", "error": str(e)})


@celery_app.task(name="unified_api.workers.tasks.edgar.backfill_filings")
def backfill_edgar_filings():
    """Advance the bounded historical EDGAR cursor without blocking current data."""
    logger.info("Starting EDGAR historical backfill")
    _start_source_job("edgar_backfill")
    try:
        import asyncio
        from unified_api.services.edgar_ingestion import run_edgar_sync

        result = asyncio.run(run_edgar_sync())
        logger.info("EDGAR historical backfill complete", **result)
        return _finish_source_job("edgar_backfill", result)
    except Exception as e:
        logger.error("EDGAR historical backfill failed", error=str(e))
        return _finish_source_job(
            "edgar_backfill",
            {"status": "failed", "lane": "backfill", "error": str(e)},
        )


@celery_app.task(name="unified_api.workers.tasks.edgar.company_identities")
def audit_sec_company_identity_records():
    """Audit a bounded CIK batch against official SEC submissions records."""
    logger.info("Starting SEC company identity audit")
    _start_source_job("sec_company_identity")
    try:
        from unified_api.services.sec_company_identity import (
            audit_sec_company_identities,
        )

        result = audit_sec_company_identities(batch_size=100)
        logger.info("SEC company identity audit complete", **result)
        return _finish_source_job("sec_company_identity", result)
    except Exception as exc:
        logger.error("SEC company identity audit failed", error=str(exc))
        return _finish_source_job(
            "sec_company_identity",
            {"status": "failed", "error": str(exc)},
        )


def _sync_clinicaltrials_lane(lane: str):
    source_key = f"clinicaltrials_{lane}"
    logger.info("Starting ClinicalTrials.gov sync", lane=lane)
    _start_source_job(source_key)
    try:
        from unified_api.services.clinical_trials import sync_clinical_trials

        result = sync_clinical_trials(lane)
        logger.info("ClinicalTrials.gov sync complete", **result)
        return _finish_source_job(source_key, result)
    except Exception as exc:
        logger.error("ClinicalTrials.gov sync failed", lane=lane, error=str(exc))
        return _finish_source_job(
            source_key,
            {"status": "failed", "lane": lane, "error": str(exc)},
        )


@celery_app.task(name="unified_api.workers.tasks.clinicaltrials.recent")
def sync_clinicaltrials_recent():
    """Refresh the latest published ClinicalTrials.gov changes."""
    return _sync_clinicaltrials_lane("recent")


@celery_app.task(name="unified_api.workers.tasks.clinicaltrials.backfill")
def backfill_clinicaltrials():
    """Advance the historical ClinicalTrials.gov cursor."""
    return _sync_clinicaltrials_lane("backfill")


@celery_app.task(name="unified_api.workers.tasks.enrichment.extract_financial_terms")
def extract_cortellis_financial_terms():
    """Normalize one resumable batch of Cortellis finance JSON."""
    logger.info("Starting Cortellis financial term extraction")
    try:
        from unified_api.services.database import get_cortellis_session
        from unified_api.services.financial_terms import extract_financial_term_batch

        with get_cortellis_session() as session:
            result = extract_financial_term_batch(session, batch_size=1000)
        log_result = {key: value for key, value in result.items() if key != "sample"}
        logger.info("Cortellis financial term extraction complete", **log_result)
        return result
    except Exception as e:
        logger.error("Cortellis financial term extraction failed", error=str(e))
        return {"status": "failed", "error": str(e)}


@celery_app.task(name="unified_api.workers.tasks.enrichment.rebuild_financial_terms")
def rebuild_cortellis_financial_terms():
    """Run the versioned financial-term backfill serially to completion."""
    logger.info("Starting Cortellis financial term rebuild")
    try:
        import time

        from unified_api.services.database import get_cortellis_session
        from unified_api.services.financial_terms import extract_financial_term_batch

        totals = {"batches": 0, "processed": 0, "terms_extracted": 0, "errors": 0}
        busy_retries = 0
        with get_cortellis_session() as session:
            for _ in range(200):
                result = extract_financial_term_batch(session, batch_size=1000)
                if result.get("status") == "busy":
                    session.rollback()
                    busy_retries += 1
                    if busy_retries > 40:
                        return {**totals, "status": "busy", "busy_retries": busy_retries}
                    time.sleep(0.25)
                    continue
                busy_retries = 0
                session.commit()
                processed = int(result.get("processed") or 0)
                totals["batches"] += 1
                totals["processed"] += processed
                totals["terms_extracted"] += int(result.get("terms_extracted") or 0)
                totals["errors"] += int(result.get("errors") or 0)
                if processed == 0:
                    break
        result = {**totals, "status": "completed", "busy_retries": busy_retries}
        logger.info("Cortellis financial term rebuild complete", **result)
        return result
    except Exception as exc:
        logger.error("Cortellis financial term rebuild failed", error=str(exc))
        return {"status": "failed", "error": str(exc)}


@celery_app.task(
    name=(
        "unified_api.workers.tasks.enrichment."
        "extract_contract_financial_clauses"
    )
)
def extract_contract_financial_clauses():
    """Normalize one resumable batch of explicit contract financial clauses."""
    logger.info("Starting contract financial clause extraction")
    try:
        from unified_api.services.contract_financial_clauses import (
            extract_contract_financial_clause_batch,
        )
        from unified_api.services.database import get_cortellis_session

        with get_cortellis_session() as session:
            result = extract_contract_financial_clause_batch(
                session,
                batch_size=1000,
            )
        log_result = {
            key: value for key, value in result.items() if key != "sample"
        }
        logger.info("Contract financial clause extraction complete", **log_result)
        return result
    except Exception as exc:
        logger.error("Contract financial clause extraction failed", error=str(exc))
        return {"status": "failed", "error": str(exc)}


@celery_app.task(
    name=(
        "unified_api.workers.tasks.enrichment."
        "rebuild_contract_financial_clauses"
    )
)
def rebuild_contract_financial_clauses():
    """Run the deterministic contract-clause backfill to completion."""
    logger.info("Starting contract financial clause rebuild")
    try:
        import time

        from unified_api.services.contract_financial_clauses import (
            extract_contract_financial_clause_batch,
        )
        from unified_api.services.database import get_cortellis_session

        totals = {"batches": 0, "processed": 0, "clauses_extracted": 0, "errors": 0}
        busy_retries = 0
        with get_cortellis_session() as session:
            for _ in range(50):
                result = extract_contract_financial_clause_batch(
                    session,
                    batch_size=1000,
                )
                if result.get("status") == "busy":
                    session.rollback()
                    busy_retries += 1
                    if busy_retries > 40:
                        return {
                            **totals,
                            "status": "busy",
                            "busy_retries": busy_retries,
                        }
                    time.sleep(0.25)
                    continue
                busy_retries = 0
                session.commit()
                processed = int(result.get("processed") or 0)
                totals["batches"] += 1
                totals["processed"] += processed
                totals["clauses_extracted"] += int(
                    result.get("clauses_extracted") or 0
                )
                totals["errors"] += int(result.get("errors") or 0)
                if processed == 0:
                    break
        result = {**totals, "status": "completed", "busy_retries": busy_retries}
        logger.info("Contract financial clause rebuild complete", **result)
        return result
    except Exception as exc:
        logger.error("Contract financial clause rebuild failed", error=str(exc))
        return {"status": "failed", "error": str(exc)}


@celery_app.task(
    name=(
        "unified_api.workers.tasks.enrichment."
        "extract_deal_clinical_trial_links"
    )
)
def extract_deal_clinical_trial_links():
    """Advance exact Cortellis NCT-citation extraction in one bounded batch."""
    logger.info("Starting exact deal-to-trial citation extraction")
    try:
        from unified_api.services.database import get_cortellis_session
        from unified_api.services.deal_evidence_timeline import (
            extract_deal_trial_link_batch,
        )

        with get_cortellis_session() as session:
            result = extract_deal_trial_link_batch(session, batch_size=5000)
        logger.info("Exact deal-to-trial citation extraction complete", **result)
        return result
    except Exception as exc:
        logger.error("Exact deal-to-trial citation extraction failed", error=str(exc))
        return {"status": "failed", "error": str(exc)}


@celery_app.task(
    name=(
        "unified_api.workers.tasks.enrichment."
        "rebuild_deal_clinical_trial_links"
    )
)
def rebuild_deal_clinical_trial_links():
    """Run the exact NCT-citation backfill serially to completion."""
    logger.info("Starting exact deal-to-trial citation rebuild")
    try:
        import time

        from unified_api.services.database import get_cortellis_session
        from unified_api.services.deal_evidence_timeline import (
            extract_deal_trial_link_batch,
        )

        totals = {
            "batches": 0,
            "processed": 0,
            "citation_mentions": 0,
            "errors": 0,
        }
        busy_retries = 0
        with get_cortellis_session() as session:
            for _ in range(50):
                result = extract_deal_trial_link_batch(session, batch_size=5000)
                if result.get("status") == "busy":
                    session.rollback()
                    busy_retries += 1
                    if busy_retries > 40:
                        return {
                            **totals,
                            "status": "busy",
                            "busy_retries": busy_retries,
                        }
                    time.sleep(0.25)
                    continue
                busy_retries = 0
                session.commit()
                processed = int(result.get("processed") or 0)
                totals["batches"] += 1
                totals["processed"] += processed
                totals["citation_mentions"] += int(
                    result.get("citation_mentions") or 0
                )
                totals["errors"] += int(result.get("errors") or 0)
                if processed == 0:
                    break
        result = {**totals, "status": "completed", "busy_retries": busy_retries}
        logger.info("Exact deal-to-trial citation rebuild complete", **result)
        return result
    except Exception as exc:
        logger.error("Exact deal-to-trial citation rebuild failed", error=str(exc))
        return {"status": "failed", "error": str(exc)}


@celery_app.task(name="unified_api.workers.tasks.enrichment.pubchem_identifiers")
def enrich_pubchem_identifiers():
    """Resolve one bounded batch of Cortellis drug names against PubChem."""
    logger.info("Starting PubChem identifier enrichment")
    try:
        from unified_api.services.pubchem_enrichment import enrich_pubchem_batch

        result = enrich_pubchem_batch(batch_size=500)
        logger.info("PubChem identifier enrichment complete", **result)
        return result
    except Exception as e:
        logger.error("PubChem identifier enrichment failed", error=str(e))
        return {"status": "failed", "error": str(e)}


@celery_app.task(name="unified_api.workers.tasks.enrichment.chembl_identifiers")
def enrich_chembl_drug_identifiers():
    """Map PubChem-confirmed structures to ChEMBL in one bounded batch."""
    logger.info("Starting ChEMBL identifier enrichment")
    _start_source_job("chembl")
    try:
        from unified_api.services.public_drug_enrichment import (
            enrich_chembl_identifiers,
        )

        result = enrich_chembl_identifiers(batch_size=100)
        logger.info("ChEMBL identifier enrichment complete", **result)
        return _finish_source_job("chembl", result)
    except Exception as exc:
        logger.error("ChEMBL identifier enrichment failed", error=str(exc))
        return _finish_source_job(
            "chembl", {"status": "failed", "error": str(exc)}
        )


@celery_app.task(name="unified_api.workers.tasks.enrichment.open_targets_profiles")
def enrich_open_targets_drug_profiles():
    """Retain Open Targets profiles, indications, and canonical targets."""
    logger.info("Starting Open Targets drug enrichment")
    _start_source_job("open_targets")
    try:
        from unified_api.services.public_drug_enrichment import (
            enrich_open_targets_profiles,
        )

        result = enrich_open_targets_profiles(batch_size=10)
        logger.info("Open Targets drug enrichment complete", **result)
        return _finish_source_job("open_targets", result)
    except Exception as exc:
        logger.error("Open Targets drug enrichment failed", error=str(exc))
        return _finish_source_job(
            "open_targets", {"status": "failed", "error": str(exc)}
        )


@celery_app.task(name="unified_api.workers.tasks.enrichment.uniprot_targets")
def enrich_uniprot_target_records():
    """Retain reviewed UniProt records for exact Open Targets accessions."""
    logger.info("Starting UniProt target enrichment")
    _start_source_job("uniprot")
    try:
        from unified_api.services.uniprot_enrichment import enrich_uniprot_targets

        result = enrich_uniprot_targets(batch_size=50)
        logger.info("UniProt target enrichment complete", **result)
        return _finish_source_job("uniprot", result)
    except Exception as exc:
        logger.error("UniProt target enrichment failed", error=str(exc))
        return _finish_source_job(
            "uniprot", {"status": "failed", "error": str(exc)}
        )


@celery_app.task(name="unified_api.workers.tasks.enrichment.europe_pmc_targets")
def enrich_europe_pmc_target_records():
    """Advance one exact target-literature query by one durable page."""
    logger.info("Starting Europe PMC target literature enrichment")
    _start_source_job("europe_pmc")
    try:
        from unified_api.services.europe_pmc_enrichment import (
            enrich_europe_pmc_target_literature,
        )

        result = enrich_europe_pmc_target_literature()
        logger.info("Europe PMC target literature enrichment complete", **result)
        return _finish_source_job("europe_pmc", result)
    except Exception as exc:
        logger.error("Europe PMC target literature enrichment failed", error=str(exc))
        return _finish_source_job(
            "europe_pmc", {"status": "failed", "error": str(exc)}
        )


@celery_app.task(name="unified_api.workers.tasks.cortellis.sync_deals")
def sync_cortellis_deals():
    """
    Sync deals from Cortellis API using incremental sync.
    Falls back to full sync if no previous sync exists.
    """
    logger.info("Starting Cortellis sync")
    _start_source_job("cortellis")
    try:
        if not settings.cortellis_api_username or not settings.cortellis_api_password:
            logger.warning("Cortellis API credentials not configured, skipping sync")
            return _finish_source_job(
                "cortellis", {"status": "skipped", "reason": "no credentials"}
            )

        sync_service = _cortellis_sync_service()
        cortellis_config = sync_service.config.cortellis
        sync_log = sync_service.incremental_sync(
            batch_size=30,
            overlap_days=settings.cortellis_sync_overlap_days,
        )

        result = {
            "status": sync_log.status,
            "sync_type": sync_log.sync_type,
            "records_processed": sync_log.records_processed,
            "records_created": getattr(sync_log, 'records_created', 0),
            "records_updated": sync_log.records_updated,
            "contracts_downloaded": sync_log.contracts_downloaded,
        }
        if sync_log.error_message:
            result["error"] = sync_log.error_message

        # A valid incremental window does not prove that an older full-sync
        # batch was never omitted.  Compare the source catalog cardinality on
        # every run and expose the source watermark in the common payload.
        from sqlalchemy import text
        from src.api_client import CortellisClient
        from src.cortellis_catalog import (
            assess_catalog_cardinality,
            ensure_catalog_exclusion_schema,
            read_catalog_proof,
        )
        from unified_api.services.database import get_cortellis_session

        with CortellisClient(cortellis_config) as client:
            catalog_total = client.search_deals("*", offset=0, hits=1).total_results
        with get_cortellis_session() as session:
            ensure_catalog_exclusion_schema(session)
            snapshot = session.execute(text("""
                SELECT COUNT(*) AS local_total,
                       MAX(date_change_last) AS source_cursor,
                       (SELECT COUNT(*)
                        FROM cortellis_catalog_exclusions) AS exclusion_total
                FROM deals
            """)).mappings().one()
            proof = read_catalog_proof(session)
        cardinality = assess_catalog_cardinality(
            advertised_total=catalog_total,
            local_total=int(snapshot["local_total"]),
            exclusion_total=int(snapshot["exclusion_total"]),
            verified_retrievable_total=proof.get("retrievable_total"),
        )
        result.update({
            **cardinality,
            "catalog_verified_at": (
                proof["verified_at"].isoformat()
                if proof.get("verified_at") else None
            ),
            "cursor": (
                snapshot["source_cursor"].isoformat()
                if snapshot["source_cursor"] else None
            ),
            "source_data_at": (
                snapshot["source_cursor"].isoformat()
                if snapshot["source_cursor"] else None
            ),
        })
        if not cardinality["catalog_cardinality_complete"] and result["status"] == "completed":
            result["status"] = "partial"
            if proof:
                result["error"] = (
                    "Cortellis verified catalog/local count mismatch: "
                    f"verified_source={proof['retrievable_total']}, "
                    f"eligible_local={cardinality['eligible_local_total']}, "
                    f"retained_local_only={cardinality['catalog_exclusions']}"
                )
            else:
                result["error"] = (
                    "Cortellis advertised catalog/local count mismatch before "
                    "the first exhaustive proof: "
                    f"source={catalog_total}, "
                    f"eligible_local={cardinality['eligible_local_total']}"
                )
        logger.info("Cortellis sync complete", **result)
        return _finish_source_job("cortellis", result)

    except Exception as e:
        logger.error("Cortellis sync failed", error=str(e))
        return _finish_source_job("cortellis", {"status": "failed", "error": str(e)})


@celery_app.task(name="unified_api.workers.tasks.cortellis.reconcile_catalog")
def reconcile_cortellis_catalog():
    """Restore records omitted by historical full-sync batch failures."""
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_engine

    # This audit can run for many minutes and may be triggered manually while a
    # scheduled invocation is queued.  Hold a session-level PostgreSQL lock for
    # the whole task so a duplicate cannot double API traffic or overwrite the
    # shared source-job state.
    lock_connection = get_cortellis_engine().connect()
    acquired = bool(lock_connection.execute(text(
        "SELECT pg_try_advisory_lock("
        "hashtext('onebd_cortellis_catalog_reconciliation'))"
    )).scalar())
    if not acquired:
        lock_connection.close()
        logger.info("Skipping duplicate Cortellis catalog reconciliation")
        return {
            "status": "skipped",
            "reason": "Cortellis catalog reconciliation already running",
        }

    try:
        logger.info("Starting Cortellis catalog reconciliation")
        _start_source_job("cortellis_catalog")
        if not settings.cortellis_api_username or not settings.cortellis_api_password:
            return _finish_source_job(
                "cortellis_catalog",
                {"status": "skipped", "reason": "no credentials"},
            )
        try:
            result = _cortellis_sync_service().reconcile_catalog(
                max_missing=settings.cortellis_catalog_repair_limit,
                scan_workers=settings.cortellis_catalog_scan_workers,
                download_contracts=False,
            )
            logger.info("Cortellis catalog reconciliation complete", **result)
            return _finish_source_job("cortellis_catalog", result)
        except Exception as exc:
            logger.error("Cortellis catalog reconciliation failed", error=str(exc))
            return _finish_source_job(
                "cortellis_catalog", {"status": "failed", "error": str(exc)}
            )
    finally:
        try:
            lock_connection.execute(text(
                "SELECT pg_advisory_unlock("
                "hashtext('onebd_cortellis_catalog_reconciliation'))"
            ))
        finally:
            lock_connection.close()


@celery_app.task(name="unified_api.workers.tasks.cortellis.scan_contract_metadata")
def scan_cortellis_contract_metadata():
    """Advance the durable all-deal contract metadata coverage scan."""
    logger.info("Starting Cortellis contract metadata scan")
    _start_source_job("cortellis_contracts")
    if not settings.cortellis_api_username or not settings.cortellis_api_password:
        return _finish_source_job(
            "cortellis_contracts",
            {"status": "skipped", "reason": "no credentials"},
        )
    try:
        from unified_api.services.cortellis_contract_sync import (
            sync_contract_metadata_batch,
        )

        result = sync_contract_metadata_batch(
            batch_size=settings.cortellis_contract_scan_batch_size,
            workers=settings.cortellis_contract_scan_workers,
        )
        log_result = {key: value for key, value in result.items() if key != "error"}
        logger.info("Cortellis contract metadata scan complete", **log_result)
        return _finish_source_job("cortellis_contracts", result)
    except Exception as exc:
        logger.error("Cortellis contract metadata scan failed", error=str(exc))
        return _finish_source_job(
            "cortellis_contracts",
            {"status": "failed", "error": str(exc)},
        )


@celery_app.task(name="unified_api.workers.tasks.cortellis.scan_deal_api_coverage")
def scan_cortellis_deal_api_coverage():
    """Archive exact expanded responses and deal-linked source citations."""
    logger.info("Starting Cortellis deal API coverage scan")
    _start_source_job("cortellis_deal_api")
    if not settings.cortellis_api_username or not settings.cortellis_api_password:
        return _finish_source_job(
            "cortellis_deal_api",
            {"status": "skipped", "reason": "no credentials"},
        )
    try:
        from unified_api.services.cortellis_deal_api_sync import (
            sync_deal_api_coverage_batch,
        )

        result = sync_deal_api_coverage_batch(
            batch_size=settings.cortellis_deal_api_scan_batch_size,
            workers=settings.cortellis_deal_api_scan_workers,
        )
        log_result = {key: value for key, value in result.items() if key != "error"}
        logger.info("Cortellis deal API coverage scan complete", **log_result)
        return _finish_source_job("cortellis_deal_api", result)
    except Exception as exc:
        logger.error("Cortellis deal API coverage scan failed", error=str(exc))
        return _finish_source_job(
            "cortellis_deal_api",
            {"status": "failed", "error": str(exc)},
        )


@celery_app.task(name="unified_api.workers.tasks.graph.sync_all")
def sync_graph():
    """Sync all data to Neo4j graph database."""
    logger.info("Starting graph sync")
    _start_source_job("neo4j")
    try:
        from unified_api.services.graph_sync import get_graph_sync_service
        service = get_graph_sync_service()
        results = service.full_sync()
        from sqlalchemy import text
        from unified_api.services.database import get_cortellis_session

        with get_cortellis_session() as session:
            source_cursor = session.execute(text(
                "SELECT MAX(date_change_last) FROM deals"
            )).scalar()
        results.update({
            "cursor": source_cursor.isoformat() if source_cursor else None,
            "source_data_at": source_cursor.isoformat() if source_cursor else None,
        })
        logger.info("Graph sync complete", **results)
        return _finish_source_job("neo4j", {"status": "completed", **results})
    except Exception as e:
        logger.error("Graph sync failed", error=str(e))
        return _finish_source_job("neo4j", {"status": "failed", "error": str(e)})


@celery_app.task(name="unified_api.workers.tasks.monitoring.source_jobs")
def monitor_scheduled_source_jobs():
    """Classify source freshness and emit deduplicated alert/recovery events."""
    try:
        from unified_api.services.source_monitoring import monitor_source_jobs

        return monitor_source_jobs()
    except Exception as e:
        logger.error("Source job monitoring failed", error=str(e))
        return {"status": "failed", "error": str(e)}


@celery_app.task(name="unified_api.workers.tasks.graph.link_deals_to_filings")
def link_deals_to_filings():
    """
    Auto-link Cortellis deals to SEC EDGAR filings.
    Matches deals to filings based on cross-referenced companies + date proximity.
    """
    logger.info("Starting deal-filing linking")
    try:
        from sqlalchemy import text
        from unified_api.services.database import get_cortellis_session, get_edgar_source_session

        links_created = 0
        deals_checked = 0

        # Get cross-referenced company mappings (cortellis_id -> edgar_company_id via CIK)
        # First get CIK mappings from xref table
        with get_edgar_source_session() as esession:
            edgar_cik_map = {}
            edgar_companies = esession.execute(text(
                "SELECT id, cik FROM companies WHERE cik IS NOT NULL AND cik <> ''"
            )).fetchall()
            for ec in edgar_companies:
                edgar_cik_map[ec.cik.lstrip('0')] = ec.id
            logger.info(f"Loaded {len(edgar_cik_map)} Edgar companies with CIK")

        with get_cortellis_session() as csession:
            # Legacy production installations created company_xref before the
            # durable Edgar ID column was added to the repository schema.
            csession.execute(text("""
                ALTER TABLE company_xref
                ADD COLUMN IF NOT EXISTS edgar_company_id BIGINT
            """))
            csession.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_company_xref_edgar_company
                ON company_xref (edgar_company_id)
            """))
            xrefs = csession.execute(text("""
                SELECT cortellis_id, edgar_company_id, cik
                FROM company_xref
                WHERE edgar_company_id IS NOT NULL
                   OR (cik IS NOT NULL AND cik <> '')
            """)).fetchall()
            # Prefer the reviewed durable cross-reference; use CIK only as a
            # backwards-compatible fallback for older xref rows.
            xref_map = {}
            xref_backfill = []
            for row in xrefs:
                if row.edgar_company_id is not None:
                    xref_map[row.cortellis_id] = row.edgar_company_id
                    continue
                cik_normalized = row.cik.lstrip('0') if row.cik else None
                if cik_normalized and cik_normalized in edgar_cik_map:
                    xref_map[row.cortellis_id] = edgar_cik_map[cik_normalized]
                    xref_backfill.append({
                        "cortellis_id": row.cortellis_id,
                        "edgar_company_id": edgar_cik_map[cik_normalized],
                    })
            if xref_backfill:
                csession.execute(text("""
                    UPDATE company_xref
                    SET edgar_company_id = :edgar_company_id,
                        updated_at = NOW()
                    WHERE cortellis_id = :cortellis_id
                      AND edgar_company_id IS NULL
                """), xref_backfill)
                csession.commit()
            logger.info(f"Loaded {len(xref_map)} company cross-references with Edgar match")

            if not xref_map:
                return {"status": "completed", "links_created": 0, "reason": "no cross-references"}

            # Create linking table if not exists
            csession.execute(text("""
                CREATE TABLE IF NOT EXISTS deal_filing_links (
                    id SERIAL PRIMARY KEY,
                    deal_id INTEGER NOT NULL,
                    edgar_document_id BIGINT NOT NULL,
                    edgar_company_id BIGINT NOT NULL,
                    match_type VARCHAR(50) NOT NULL,
                    date_distance_days INTEGER,
                    confidence FLOAT DEFAULT 0.5,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(deal_id, edgar_document_id)
                )
            """))
            csession.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_dfl_deal_id ON deal_filing_links(deal_id);
                CREATE INDEX IF NOT EXISTS idx_dfl_edgar_doc ON deal_filing_links(edgar_document_id);
            """))
            csession.commit()

            # Get deals with cross-referenced companies and dates
            cortellis_ids = list(xref_map.keys())
            insert_links = text("""
                INSERT INTO deal_filing_links (
                    deal_id, edgar_document_id, edgar_company_id,
                    match_type, date_distance_days, confidence
                ) VALUES (
                    :deal_id, :doc_id, :edgar_company_id,
                    :match_type, :days_diff, :confidence
                )
                ON CONFLICT (deal_id, edgar_document_id) DO NOTHING
            """)
            filings_loaded = 0
            query_batches = 0
            from unified_api.services.deal_filing_linker import (
                build_bulk_deal_filing_links,
            )

            # Each batch performs one Cortellis deal query, one EDGAR filing
            # query, and one existing-link query. The previous implementation
            # opened an EDGAR session and ran a query for every deal.
            for chunk_start in range(0, len(cortellis_ids), 500):
                chunk_ids = cortellis_ids[chunk_start:chunk_start + 500]
                deals = csession.execute(text("""
                    SELECT d.id as deal_id, dc.company_id as cortellis_company_id,
                           d.date_start
                    FROM deals d
                    JOIN deal_companies dc ON dc.deal_id = d.id
                    WHERE dc.company_id = ANY(:company_ids)
                      AND d.date_start IS NOT NULL
                    ORDER BY d.date_start DESC
                """), {"company_ids": chunk_ids}).mappings().all()

                deals_checked += len(deals)
                if not deals:
                    continue
                deal_ids = list({int(deal["deal_id"]) for deal in deals})
                existing = csession.execute(text("""
                    SELECT deal_id, edgar_document_id
                    FROM deal_filing_links
                    WHERE deal_id = ANY(:deal_ids)
                """), {"deal_ids": deal_ids}).all()
                existing_pairs = {(row.deal_id, row.edgar_document_id) for row in existing}
                edgar_company_ids = list({
                    xref_map[int(deal["cortellis_company_id"])] for deal in deals
                })
                min_date = min(deal["date_start"] for deal in deals)
                max_date = max(deal["date_start"] for deal in deals)
                with get_edgar_source_session() as esession:
                    filings = esession.execute(text("""
                            SELECT d.id AS doc_id, d.doc_type,
                                   rd.company_id AS edgar_company_id,
                                   rd.filing_date
                            FROM documents d
                            JOIN raw_documents rd ON rd.id = d.raw_document_id
                            WHERE rd.company_id = ANY(:company_ids)
                              AND rd.filing_date BETWEEN :min_date - INTERVAL '30 days'
                                                     AND :max_date + INTERVAL '30 days'
                              AND d.parse_ok = true
                        """), {
                            "company_ids": edgar_company_ids,
                            "min_date": min_date,
                            "max_date": max_date,
                        }).mappings().all()

                query_batches += 1
                filings_loaded += len(filings)
                links = build_bulk_deal_filing_links(
                    deals,
                    filings,
                    xref_map,
                    existing_pairs=existing_pairs,
                )
                for start in range(0, len(links), 5000):
                    result = csession.execute(insert_links, links[start:start + 5000])
                    links_created += max(0, result.rowcount or 0)

                csession.commit()
                logger.info(
                    "Bulk deal-filing link progress",
                    deals_checked=deals_checked,
                    filings_loaded=filings_loaded,
                    links_created=links_created,
                    query_batches=query_batches,
                )

        logger.info(
            "Deal-filing linking complete",
            links_created=links_created,
            deals_checked=deals_checked,
            filings_loaded=filings_loaded,
            query_batches=query_batches,
        )
        return {
            "status": "completed",
            "links_created": links_created,
            "deals_checked": deals_checked,
            "filings_loaded": filings_loaded,
            "query_batches": query_batches,
        }

    except Exception as e:
        logger.error("Deal-filing linking failed", error=str(e))
        return {"status": "failed", "error": str(e)}


@celery_app.task(name="unified_api.workers.tasks.process.parse_document")
def parse_document(document_id: int, source: str):
    """
    Parse a document (HTML or PDF) and extract text.
    """
    logger.info("Parsing document", document_id=document_id, source=source)
    # TODO: Import parser service
    return {"status": "completed", "document_id": document_id}


@celery_app.task(name="unified_api.workers.tasks.process.chunk_and_embed")
def chunk_and_embed(document_id: int, source: str):
    """
    Chunk document text and generate embeddings.
    """
    logger.info("Chunking and embedding", document_id=document_id, source=source)
    # TODO: Import chunker and embedder services
    return {"status": "completed", "document_id": document_id, "chunks_created": 0}


@celery_app.task(name="unified_api.workers.tasks.extract.extract_deal")
def extract_deal_from_filing(filing_id: int):
    """
    Extract deal information from an SEC 8-K filing using LLM.
    """
    logger.info("Extracting deal from filing", filing_id=filing_id)
    # TODO: Import extraction service
    return {"status": "completed", "filing_id": filing_id, "deal_extracted": False}


@celery_app.task(name="unified_api.workers.tasks.match.match_company")
def match_company(company_name: str, source: str):
    """
    Match a company name to existing entities using entity resolution.
    Uses trigram similarity for fuzzy matching.
    """
    logger.info("Matching company", company_name=company_name, source=source)
    # TODO: Import company matcher service
    return {"status": "completed", "company_name": company_name, "match_id": None}


# ============================================
# ALERT TASKS
# ============================================

@celery_app.task(name="unified_api.workers.tasks.alerts.check_alerts")
def check_alerts():
    """
    Check all saved searches marked as alerts for new matching deals.
    Sends notifications for any new matches since last run.
    """
    from datetime import datetime, timedelta
    from sqlalchemy import text

    logger.info("Starting deal alert check")

    try:
        from unified_api.services.database import get_cortellis_session

        alerts_checked = 0
        notifications_sent = 0

        with get_cortellis_session() as session:
            # Get all alert subscriptions
            result = session.execute(text("""
                SELECT id, user_id, name, criteria, last_run_at
                FROM saved_searches
                WHERE is_alert = TRUE
            """))

            alerts = result.fetchall()

            for alert in alerts:
                alerts_checked += 1
                last_run = alert.last_run_at or datetime.utcnow() - timedelta(days=1)
                criteria = alert.criteria

                # Build query based on saved criteria
                conditions = ["d.created_at > :last_run"]
                params = {"last_run": last_run}

                if criteria.get("company"):
                    conditions.append("""
                        d.id IN (
                            SELECT dc.deal_id FROM deal_companies dc
                            JOIN companies c ON c.id = dc.company_id
                            WHERE c.name ILIKE :company
                        )
                    """)
                    params["company"] = f"%{criteria['company']}%"

                if criteria.get("therapy_area"):
                    conditions.append("""
                        d.id IN (
                            SELECT d2.id FROM deals d2
                            JOIN therapy_areas ta ON ta.id = d2.therapy_area_id
                            WHERE ta.name ILIKE :therapy_area
                        )
                    """)
                    params["therapy_area"] = f"%{criteria['therapy_area']}%"

                if criteria.get("indication"):
                    conditions.append("""
                        d.id IN (
                            SELECT di.deal_id FROM deal_indications di
                            JOIN indications i ON i.id = di.indication_id
                            WHERE i.name ILIKE :indication
                        )
                    """)
                    params["indication"] = f"%{criteria['indication']}%"

                if criteria.get("deal_type"):
                    conditions.append("d.agreement_type ILIKE :deal_type")
                    params["deal_type"] = f"%{criteria['deal_type']}%"

                where_clause = " AND ".join(conditions)

                # Find new matching deals
                query = f"""
                    SELECT d.id, d.title, d.date_start::text, d.status
                    FROM deals d
                    WHERE {where_clause}
                    ORDER BY d.date_start DESC
                    LIMIT 20
                """

                new_deals_result = session.execute(text(query), params)
                new_deals = new_deals_result.fetchall()

                if new_deals:
                    # Store notification for this alert
                    for deal in new_deals:
                        session.execute(text("""
                            INSERT INTO deal_notes (
                                deal_id, user_id, content, is_private
                            ) VALUES (
                                :deal_id, :user_id,
                                :content, TRUE
                            )
                            ON CONFLICT DO NOTHING
                        """), {
                            "deal_id": deal.id,
                            "user_id": alert.user_id,
                            "content": f"[Alert: {alert.name}] New deal matching your saved search criteria.",
                        })
                        notifications_sent += 1
                    
                    # Send email notification
                    deals_for_email = [{
                        "id": d.id,
                        "title": d.title,
                        "date": d.date_start,
                        "status": d.status,
                    } for d in new_deals]
                    send_alert_email.delay(
                        user_id=str(alert.user_id),
                        alert_name=alert.name,
                        deals=deals_for_email,
                    )

                # Update last_run_at
                session.execute(text("""
                    UPDATE saved_searches
                    SET last_run_at = NOW()
                    WHERE id = :alert_id
                """), {"alert_id": alert.id})

            session.commit()

        logger.info(
            "Deal alert check completed",
            alerts_checked=alerts_checked,
            notifications_sent=notifications_sent,
        )

        return {
            "status": "completed",
            "alerts_checked": alerts_checked,
            "notifications_sent": notifications_sent,
        }

    except Exception as e:
        logger.error("Failed to check alerts", error=str(e))
        return {"status": "failed", "error": str(e)}


@celery_app.task(name="unified_api.workers.tasks.alerts.company_entrants")
def check_company_entrant_alerts():
    """Persist and deduplicate first-observed indication entrant alerts."""
    from unified_api.services.company_entrant_alerts import (
        scan_company_entrant_alerts,
    )
    from unified_api.services.database import get_cortellis_session

    logger.info("Starting company entrant alert check")
    try:
        with get_cortellis_session() as session:
            result = scan_company_entrant_alerts(session)
        logger.info("Company entrant alert check complete", **result)
        return result
    except Exception as exc:
        logger.error("Company entrant alert check failed", error=str(exc))
        return {"status": "failed", "error": str(exc)}


@celery_app.task(name="unified_api.workers.tasks.alerts.send_alert_email")
def send_alert_email(user_id: str, alert_name: str, deals: list):
    """
    Send an email notification for deal alerts.
    """
    from unified_api.services.email_digest import build_digest_html, send_digest_email
    from unified_api.services.database import get_cortellis_session
    from sqlalchemy import text

    logger.info("Sending alert email", user_id=user_id, alert_name=alert_name, deal_count=len(deals))

    # Get user email
    with get_cortellis_session() as session:
        user = session.execute(text("SELECT email FROM users WHERE id = :id"), {"id": int(user_id)}).fetchone()
        if not user:
            return {"status": "skipped", "reason": "user not found"}

    sections = [
        {
            "title": f"Alert: {alert_name}",
            "content": f"{len(deals)} new deals match your saved search criteria.",
            "items": deals[:10],
        },
    ]

    html = build_digest_html(f"Deal Alert: {alert_name}", sections)
    sent = send_digest_email(user.email, f"BD Intelligence Alert — {alert_name}", html)

    return {"status": "sent" if sent else "logged", "user_id": user_id, "deals": len(deals)}


# ============================================
# DIGEST TASKS
# ============================================

@celery_app.task(name="unified_api.workers.tasks.digest.send_daily_digest")
def send_daily_digest():
    """Generate and send personalized deal and catalyst reports."""
    import datetime
    import json
    from sqlalchemy import text
    from unified_api.services.catalyst_calendar import ACTIVE_TRIAL_STATUSES
    from unified_api.services.database import get_cortellis_session
    from unified_api.services.digest_settings import ensure_digest_settings_schema
    from unified_api.services.email_digest import build_digest_html, send_digest_email

    logger.info("Generating personalized deal digests")

    # Check if today is Monday (for weekly digest users)
    is_monday = datetime.datetime.utcnow().weekday() == 0

    with get_cortellis_session() as session:
        ensure_digest_settings_schema(session)
        session.commit()

        # Get users with digest enabled
        users = session.execute(text("""
            SELECT uds.user_id, uds.email as digest_email, uds.frequency,
                   uds.therapy_areas, uds.company_ids,
                   uds.include_catalysts, uds.catalyst_days,
                   u.email as user_email
            FROM user_digest_settings uds
            JOIN users u ON u.id = uds.user_id
            WHERE uds.enabled = true
        """)).fetchall()

        sent = 0
        total_deals_sent = 0

        for user in users:
            # Skip weekly users on non-Monday
            if user.frequency == 'weekly' and not is_monday:
                logger.debug("Skipping weekly user (not Monday)", user_id=user.user_id)
                continue
            
            # Skip 'off' users
            if user.frequency == 'off':
                logger.debug("Skipping user with frequency=off", user_id=user.user_id)
                continue
            
            # Parse JSONB fields (they come as lists from PostgreSQL JSONB)
            therapy_areas = user.therapy_areas if isinstance(user.therapy_areas, list) else json.loads(user.therapy_areas or '[]')
            company_ids = user.company_ids if isinstance(user.company_ids, list) else json.loads(user.company_ids or '[]')

            # Weekly reports cover seven days; daily reports cover one. Keep all
            # preference values bound so names cannot alter the SQL statement.
            period_days = 1 if user.frequency == 'daily' else 7
            deal_params = {
                "period_days": period_days,
                "therapy_areas": json.dumps(therapy_areas),
                "company_ids": json.dumps(company_ids),
            }
            preference_filters = []
            if therapy_areas:
                preference_filters.append("""
                    d.therapy_area_id IN (
                        SELECT therapy.id
                        FROM therapy_areas therapy
                        WHERE therapy.name IN (
                            SELECT selected.value
                            FROM JSONB_ARRAY_ELEMENTS_TEXT(
                                CAST(:therapy_areas AS JSONB)
                            ) AS selected(value)
                        )
                    )
                """)
            if company_ids:
                preference_filters.append("""
                    EXISTS (
                        SELECT 1 FROM deal_companies company_link
                        WHERE company_link.deal_id = d.id
                          AND company_link.company_id IN (
                              SELECT selected.value::INTEGER
                              FROM JSONB_ARRAY_ELEMENTS_TEXT(
                                  CAST(:company_ids AS JSONB)
                              ) AS selected(value)
                          )
                    )
                """)
            preference_clause = ""
            if preference_filters:
                preference_clause = " AND (" + " OR ".join(preference_filters) + ")"
            where_clause = (
                "WHERE d.date_start >= CURRENT_DATE - "
                "CAST(:period_days AS INTEGER)" + preference_clause
            )

            # Query for personalized deals
            deals = session.execute(text(f"""
                SELECT DISTINCT d.title, d.agreement_type, d.date_start::text as date,
                       f.total_projected_current_amount as value,
                       (SELECT c.name FROM deal_companies dc JOIN companies c ON c.id = dc.company_id
                        WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal,
                       (SELECT c.name FROM deal_companies dc JOIN companies c ON c.id = dc.company_id
                        WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner
                FROM deals d
                LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
                {where_clause}
                ORDER BY f.total_projected_current_amount DESC NULLS LAST
                LIMIT 15
            """), deal_params).fetchall()

            # Count total matching deals
            deal_count = session.execute(text(f"""
                SELECT COUNT(DISTINCT d.id)
                FROM deals d
                {where_clause}
            """), deal_params).scalar()

            catalysts = []
            catalyst_count = 0
            if user.include_catalysts:
                catalyst_params = {
                    "catalyst_days": user.catalyst_days,
                    "active_statuses": list(ACTIVE_TRIAL_STATUSES),
                    "company_ids": json.dumps(company_ids),
                }
                catalyst_company_filter = ""
                if company_ids:
                    catalyst_company_filter = """
                        AND EXISTS (
                            SELECT 1 FROM clinical_trial_companies company_link
                            WHERE company_link.nct_id = trial.nct_id
                              AND company_link.company_id IN (
                                  SELECT selected.value::INTEGER
                                  FROM JSONB_ARRAY_ELEMENTS_TEXT(
                                      CAST(:company_ids AS JSONB)
                                  ) AS selected(value)
                              )
                        )
                    """
                catalyst_where = f"""
                    WHERE trial.primary_completion_date BETWEEN CURRENT_DATE
                          AND CURRENT_DATE + CAST(:catalyst_days AS INTEGER)
                      AND trial.overall_status = ANY(
                          CAST(:active_statuses AS TEXT[])
                      )
                      {catalyst_company_filter}
                """
                catalysts = session.execute(text(f"""
                    SELECT trial.nct_id, trial.brief_title,
                           trial.primary_completion_date::TEXT AS date,
                           trial.primary_completion_date_type AS date_type,
                           trial.phases, trial.lead_sponsor_name,
                           trial.source_url,
                           STRING_AGG(
                               DISTINCT linked_company.name, ', '
                               ORDER BY linked_company.name
                           ) AS companies
                    FROM clinical_trials trial
                    LEFT JOIN clinical_trial_companies company_link
                           ON company_link.nct_id = trial.nct_id
                    LEFT JOIN companies linked_company
                           ON linked_company.id = company_link.company_id
                    {catalyst_where}
                    GROUP BY trial.nct_id, trial.brief_title,
                             trial.primary_completion_date,
                             trial.primary_completion_date_type,
                             trial.phases, trial.lead_sponsor_name,
                             trial.source_url
                    ORDER BY trial.primary_completion_date, trial.nct_id
                    LIMIT 15
                """), catalyst_params).fetchall()
                catalyst_count = session.execute(text(f"""
                    SELECT COUNT(*) FROM clinical_trials trial
                    {catalyst_where}
                """), catalyst_params).scalar()

            # Build sections
            digest_type = "Daily" if user.frequency == 'daily' else "Weekly"
            sections = [
                {
                    "title": f"{digest_type} Summary",
                    "stats": [
                        {"label": "New Deals", "value": str(deal_count)},
                        *([{
                            "label": f"Catalysts (next {user.catalyst_days} days)",
                            "value": str(catalyst_count),
                        }] if user.include_catalysts else []),
                    ],
                },
                {
                    "title": "Notable Deals" + (" Matching Your Interests" if (therapy_areas or company_ids) else ""),
                    "items": [{
                        "title": d.title,
                        "principal": d.principal,
                        "partner": d.partner,
                        "value": float(d.value) if d.value else None,
                        "date": d.date,
                    } for d in deals],
                },
            ]

            if user.include_catalysts:
                sections.append({
                    "title": (
                        f"Upcoming Clinical Catalysts — Next "
                        f"{user.catalyst_days} Days"
                    ),
                    "type": "catalysts",
                    "items": [{
                        "title": catalyst.brief_title,
                        "nct_id": catalyst.nct_id,
                        "date": catalyst.date,
                        "date_type": catalyst.date_type,
                        "phase": ", ".join(catalyst.phases or []),
                        "sponsor": catalyst.lead_sponsor_name,
                        "companies": catalyst.companies,
                        "source_url": catalyst.source_url,
                    } for catalyst in catalysts],
                })

            html = build_digest_html(
                f"Your {digest_type} Intelligence Digest",
                sections,
            )

            # Use digest_email if set, otherwise fall back to user_email
            recipient_email = user.digest_email if user.digest_email else user.user_email

            if send_digest_email(
                recipient_email,
                f"BD Intelligence — {digest_type} Intelligence Digest",
                html,
            ):
                sent += 1
                total_deals_sent += deal_count
                logger.info("Digest sent", user_id=user.user_id, email=recipient_email, deals=deal_count, frequency=user.frequency)

    logger.info("Daily digest complete", sent=sent, total_users=len(users), is_monday=is_monday)
    return {"status": "completed", "emails_sent": sent, "total_users": len(users), "is_monday": is_monday}


# ============================================
# MAINTENANCE TASKS
# ============================================

@celery_app.task(name="unified_api.workers.tasks.maintenance.refresh_materialized_views")
def refresh_materialized_views():
    """
    Refresh all materialized views for analytics performance.
    Should run after data syncs complete.
    """
    from sqlalchemy import text

    logger.info("Refreshing materialized views")

    try:
        from unified_api.services.database import get_cortellis_session

        views = [
            "mv_market_trends_yearly",
            "mv_agreement_type_stats",
            "mv_therapy_area_trends",
            "mv_company_deal_stats",
        ]

        with get_cortellis_session() as session:
            for view in views:
                session.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}"))
                logger.info(f"Refreshed {view}")
            session.commit()

        # Invalidate Redis cache after refresh
        from unified_api.services.cache import cache_invalidate
        deleted = cache_invalidate("bd:*")
        logger.info("Cache invalidated after MV refresh", keys_deleted=deleted)

        return {"status": "completed", "views_refreshed": len(views)}

    except Exception as e:
        logger.error("Failed to refresh materialized views", error=str(e))
        return {"status": "failed", "error": str(e)}


# ============================================
# PAGEINDEX TASKS
# ============================================

@celery_app.task(
    name="unified_api.workers.tasks.pageindex.batch_index_contracts",
    bind=True,
    max_retries=0,
    time_limit=7200,  # 2 hours max
)
def batch_index_contracts(self, limit: int = 500, min_words: int = 10000):
    """
    Batch pre-index contracts with PageIndex tree generation.

    Runs nightly at 3 AM via Celery Beat. Indexes the largest un-indexed
    contracts so user queries are instant (cache hit).

    Args:
        limit: Max contracts to index in this batch
        min_words: Min word count to consider
    """
    import asyncio

    logger.info(
        "Starting batch PageIndex indexing",
        limit=limit,
        min_words=min_words,
    )

    try:
        from unified_api.services.database import get_cortellis_session_factory
        from unified_api.services.batch_index import run_batch_index
        from unified_api.config import settings

        factory = get_cortellis_session_factory()
        model = settings.openai_model or "gpt-4o-2024-11-20"

        result = asyncio.run(
            run_batch_index(
                session_factory=factory,
                limit=limit,
                min_words=min_words,
                model=model,
            )
        )

        logger.info("Batch PageIndex indexing complete", **result)
        return result

    except Exception as e:
        logger.error("Batch PageIndex indexing failed", error=str(e))
        return {"status": "failed", "error": str(e)}
