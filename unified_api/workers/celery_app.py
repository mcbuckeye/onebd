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
        # Temporarily advance the historical backlog every two hours. Each run
        # is bounded and the EDGAR queue has concurrency=1, so runs cannot
        # issue concurrent SEC requests.
        "backfill-edgar-filings": {
            "task": "unified_api.workers.tasks.edgar.backfill_filings",
            "schedule": crontab(hour="*/2", minute=15),
        },
        # Sync Cortellis deals daily at 6:30 AM
        "sync-cortellis-deals": {
            "task": "unified_api.workers.tasks.cortellis.sync_deals",
            "schedule": crontab(hour=6, minute=30),
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

@celery_app.task(name="unified_api.workers.tasks.edgar.fetch_new_filings")
def fetch_new_filings():
    """
    Fetch new SEC EDGAR filings.
    Runs on rate-limited edgar queue (1 worker, 10 req/sec).
    """
    logger.info("Starting EDGAR filing fetch")
    try:
        import asyncio
        from unified_api.services.edgar_ingestion import run_edgar_recent_sync

        result = asyncio.run(run_edgar_recent_sync())
        logger.info("EDGAR filing fetch complete", **result)
        return result
    except Exception as e:
        logger.error("EDGAR filing fetch failed", error=str(e))
        return {"status": "failed", "error": str(e)}


@celery_app.task(name="unified_api.workers.tasks.edgar.backfill_filings")
def backfill_edgar_filings():
    """Advance the bounded historical EDGAR cursor without blocking current data."""
    logger.info("Starting EDGAR historical backfill")
    try:
        import asyncio
        from unified_api.services.edgar_ingestion import run_edgar_sync

        result = asyncio.run(run_edgar_sync())
        logger.info("EDGAR historical backfill complete", **result)
        return result
    except Exception as e:
        logger.error("EDGAR historical backfill failed", error=str(e))
        return {"status": "failed", "lane": "backfill", "error": str(e)}


@celery_app.task(name="unified_api.workers.tasks.enrichment.extract_financial_terms")
def extract_cortellis_financial_terms():
    """Normalize one resumable batch of Cortellis finance JSON."""
    logger.info("Starting Cortellis financial term extraction")
    try:
        from unified_api.services.database import get_cortellis_session
        from unified_api.services.financial_terms import extract_financial_term_batch

        with get_cortellis_session() as session:
            result = extract_financial_term_batch(session, batch_size=1000)
        logger.info("Cortellis financial term extraction complete", **result)
        return result
    except Exception as e:
        logger.error("Cortellis financial term extraction failed", error=str(e))
        return {"status": "failed", "error": str(e)}


@celery_app.task(name="unified_api.workers.tasks.cortellis.sync_deals")
def sync_cortellis_deals():
    """
    Sync deals from Cortellis API using incremental sync.
    Falls back to full sync if no previous sync exists.
    """
    logger.info("Starting Cortellis sync")
    try:
        from unified_api.config import settings
        from src.config import CortellisConfig, DatabaseConfig, OpenAIConfig, AppConfig
        from src.sync import SyncService

        if not settings.cortellis_api_username or not settings.cortellis_api_password:
            logger.warning("Cortellis API credentials not configured, skipping sync")
            return {"status": "skipped", "reason": "no credentials"}

        # Build config from unified settings
        cortellis_config = CortellisConfig(
            username=settings.cortellis_api_username,
            password=settings.cortellis_api_password,
            base_url=settings.cortellis_base_url,
        )
        # Parse DB URL components from the connection string
        db_url = settings.cortellis_db_url
        database_config = DatabaseConfig(
            host=db_url.split("@")[1].split(":")[0],
            port=int(db_url.split("@")[1].split(":")[1].split("/")[0]),
            database=db_url.split("/")[-1],
            user=db_url.split("://")[1].split(":")[0],
            password=db_url.split("://")[1].split(":")[1].split("@")[0],
        )
        openai_config = OpenAIConfig(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )
        app_config = AppConfig(
            cortellis=cortellis_config,
            database=database_config,
            openai=openai_config,
            sync_schedule="",
            data_dir="/app/data",
            contracts_dir="/app/data/contracts",
        )

        sync_service = SyncService(app_config)
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
        logger.info("Cortellis sync complete", **result)
        return result

    except Exception as e:
        logger.error("Cortellis sync failed", error=str(e))
        return {"status": "failed", "error": str(e)}


@celery_app.task(name="unified_api.workers.tasks.graph.sync_all")
def sync_graph():
    """Sync all data to Neo4j graph database."""
    logger.info("Starting graph sync")
    try:
        from unified_api.services.graph_sync import get_graph_sync_service
        service = get_graph_sync_service()
        results = service.full_sync()
        logger.info("Graph sync complete", **results)
        return {"status": "completed", **results}
    except Exception as e:
        logger.error("Graph sync failed", error=str(e))
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
            xrefs = csession.execute(text("""
                SELECT cortellis_id, cik
                FROM company_xref
                WHERE cik IS NOT NULL AND cik <> ''
            """)).fetchall()
            # Map cortellis_id -> edgar_company_id via CIK
            xref_map = {}
            for row in xrefs:
                cik_normalized = row.cik.lstrip('0') if row.cik else None
                if cik_normalized and cik_normalized in edgar_cik_map:
                    xref_map[row.cortellis_id] = edgar_cik_map[cik_normalized]
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

            # Get existing links to avoid duplicates
            existing = csession.execute(text("SELECT deal_id, edgar_document_id FROM deal_filing_links")).fetchall()
            existing_pairs = {(r.deal_id, r.edgar_document_id) for r in existing}
            logger.info(f"Found {len(existing_pairs)} existing links")

            # Get deals with cross-referenced companies and dates
            cortellis_ids = list(xref_map.keys())
            # Process in chunks
            for chunk_start in range(0, len(cortellis_ids), 500):
                chunk_ids = cortellis_ids[chunk_start:chunk_start + 500]
                placeholders = ",".join(str(cid) for cid in chunk_ids)

                deals = csession.execute(text(f"""
                    SELECT d.id as deal_id, dc.company_id as cortellis_company_id,
                           d.date_start, d.date_event_most_recent
                    FROM deals d
                    JOIN deal_companies dc ON dc.deal_id = d.id
                    WHERE dc.company_id IN ({placeholders})
                      AND d.date_start IS NOT NULL
                    ORDER BY d.date_start DESC
                """)).fetchall()

                deals_checked += len(deals)

                # For each deal, find matching filings by company + date window
                for deal in deals:
                    edgar_company_id = xref_map.get(deal.cortellis_company_id)
                    if not edgar_company_id:
                        continue

                    deal_date = deal.date_start

                    # Search Edgar for filings by this company within ±30 days
                    with get_edgar_source_session() as esession:
                        filings = esession.execute(text("""
                            SELECT d.id as doc_id, d.doc_type, d.title, d.published_at,
                                   rd.filing_date,
                                   ABS(EXTRACT(EPOCH FROM (rd.filing_date - :deal_date)) / 86400)::int as days_diff
                            FROM documents d
                            JOIN raw_documents rd ON rd.id = d.raw_document_id
                            WHERE rd.company_id = :edgar_company_id
                              AND rd.filing_date BETWEEN :deal_date - INTERVAL '30 days'
                                                     AND :deal_date + INTERVAL '30 days'
                              AND d.parse_ok = true
                            ORDER BY ABS(EXTRACT(EPOCH FROM (rd.filing_date - :deal_date)))
                            LIMIT 10
                        """), {
                            "edgar_company_id": edgar_company_id,
                            "deal_date": deal_date,
                        }).fetchall()

                        for filing in filings:
                            if (deal.deal_id, filing.doc_id) in existing_pairs:
                                continue

                            # Compute confidence based on date distance
                            days_diff = filing.days_diff or 30
                            confidence = max(0.3, 1.0 - (days_diff / 30.0) * 0.5)

                            csession.execute(text("""
                                INSERT INTO deal_filing_links
                                    (deal_id, edgar_document_id, edgar_company_id, match_type, date_distance_days, confidence)
                                VALUES (:deal_id, :doc_id, :edgar_company_id, :match_type, :days_diff, :confidence)
                                ON CONFLICT (deal_id, edgar_document_id) DO NOTHING
                            """), {
                                "deal_id": deal.deal_id,
                                "doc_id": filing.doc_id,
                                "edgar_company_id": edgar_company_id,
                                "match_type": f"company_date_{filing.doc_type}",
                                "days_diff": days_diff,
                                "confidence": confidence,
                            })
                            links_created += 1
                            existing_pairs.add((deal.deal_id, filing.doc_id))

                csession.commit()
                logger.info(f"Processed {deals_checked} deals, {links_created} links so far")

        logger.info("Deal-filing linking complete", links_created=links_created, deals_checked=deals_checked)
        return {"status": "completed", "links_created": links_created, "deals_checked": deals_checked}

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
    """Generate and send personalized deal digests to all subscribed users."""
    import datetime
    import json
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session
    from unified_api.services.email_digest import build_digest_html, send_digest_email

    logger.info("Generating personalized deal digests")

    # Check if today is Monday (for weekly digest users)
    is_monday = datetime.datetime.utcnow().weekday() == 0

    with get_cortellis_session() as session:
        # Ensure user_digest_settings table exists
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS user_digest_settings (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL UNIQUE,
                enabled BOOLEAN DEFAULT FALSE,
                frequency VARCHAR(20) DEFAULT 'weekly',
                therapy_areas JSONB DEFAULT '[]',
                company_ids JSONB DEFAULT '[]',
                email VARCHAR(255),
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """))
        session.commit()

        # Get users with digest enabled
        users = session.execute(text("""
            SELECT uds.user_id, uds.email as digest_email, uds.frequency,
                   uds.therapy_areas, uds.company_ids,
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

            # Build personalized deal query based on user preferences
            therapy_filter = ""
            company_filter = ""
            
            if therapy_areas and len(therapy_areas) > 0:
                # Convert Python list to PostgreSQL array format
                areas_array = "{" + ",".join(f'"{a}"' for a in therapy_areas) + "}"
                therapy_filter = f"AND EXISTS (SELECT 1 FROM deal_therapy_areas dta JOIN therapy_areas ta ON ta.id = dta.therapy_area_id WHERE dta.deal_id = d.id AND ta.name = ANY(ARRAY{areas_array}::text[]))"
            
            if company_ids and len(company_ids) > 0:
                # Add deals involving tracked companies
                company_filter = f"OR d.id IN (SELECT dc.deal_id FROM deal_companies dc WHERE dc.company_id = ANY(ARRAY{company_ids}::integer[]))"

            # Construct the full WHERE clause
            if therapy_filter or company_filter:
                # User has preferences - filter by them
                where_clause = f"""
                    WHERE (d.date_start >= CURRENT_DATE - INTERVAL '1 day' {therapy_filter})
                    {company_filter}
                """
            else:
                # No preferences - show all recent deals
                where_clause = "WHERE d.date_start >= CURRENT_DATE - INTERVAL '1 day'"

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
            """)).fetchall()

            # Count total matching deals
            deal_count = session.execute(text(f"""
                SELECT COUNT(DISTINCT d.id)
                FROM deals d
                {where_clause}
            """)).scalar()

            # Build sections
            digest_type = "Daily" if user.frequency == 'daily' else "Weekly"
            sections = [
                {
                    "title": f"{digest_type} Summary",
                    "stats": [
                        {"label": "New Deals", "value": str(deal_count)},
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

            html = build_digest_html(f"Your {digest_type} Deal Digest", sections)

            # Use digest_email if set, otherwise fall back to user_email
            recipient_email = user.digest_email if user.digest_email else user.user_email

            if send_digest_email(recipient_email, f"BD Intelligence — {digest_type} Digest", html):
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
