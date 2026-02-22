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
        # Fetch new SEC EDGAR filings daily at 2 AM
        "fetch-edgar-filings": {
            "task": "unified_api.workers.tasks.edgar.fetch_new_filings",
            "schedule": crontab(hour=2, minute=0),
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
    # TODO: Import and call actual fetch service
    return {"status": "completed", "filings_fetched": 0}


@celery_app.task(name="unified_api.workers.tasks.cortellis.sync_deals")
def sync_cortellis_deals():
    """
    Sync deals from Cortellis API.
    """
    logger.info("Starting Cortellis sync")
    # TODO: Import and call actual sync service
    return {"status": "completed", "deals_synced": 0}


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
    Auto-link Cortellis deals to SEC 8-K filings.
    Matches deals to filings based on company + date proximity.
    """
    logger.info("Starting deal-filing linking")
    # TODO: Implement matching logic
    return {"status": "completed", "links_created": 0}


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
    """Generate and send daily deal digest to all subscribed users."""
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session
    from unified_api.services.email_digest import build_digest_html, send_digest_email

    logger.info("Generating daily deal digest")

    with get_cortellis_session() as session:
        # Get yesterday's notable deals
        deals = session.execute(text("""
            SELECT d.title, d.agreement_type, d.date_start::text as date,
                   f.total_projected_current_amount as value,
                   (SELECT c.name FROM deal_companies dc JOIN companies c ON c.id = dc.company_id
                    WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal,
                   (SELECT c.name FROM deal_companies dc JOIN companies c ON c.id = dc.company_id
                    WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner
            FROM deals d
            LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
            WHERE d.date_start >= CURRENT_DATE - INTERVAL '1 day'
            ORDER BY f.total_projected_current_amount DESC NULLS LAST
            LIMIT 15
        """)).fetchall()

        deal_count = session.execute(text(
            "SELECT COUNT(*) FROM deals WHERE date_start >= CURRENT_DATE - INTERVAL '1 day'"
        )).scalar()

        # Build sections
        sections = [
            {
                "title": "Today's Summary",
                "stats": [
                    {"label": "New Deals", "value": str(deal_count)},
                ],
            },
            {
                "title": "Notable Deals",
                "items": [{
                    "title": d.title,
                    "principal": d.principal,
                    "partner": d.partner,
                    "value": float(d.value) if d.value else None,
                    "date": d.date,
                } for d in deals],
            },
        ]

        html = build_digest_html("Daily Deal Digest", sections)

        # Get subscribed users
        users = session.execute(text(
            "SELECT email FROM users WHERE role IN ('ceo', 'admin', 'vp_bd')"
        )).fetchall()

        sent = 0
        for user in users:
            if send_digest_email(user.email, "BD Intelligence — Daily Digest", html):
                sent += 1

    logger.info("Daily digest complete", sent=sent, total_users=len(users))
    return {"status": "completed", "emails_sent": sent, "deals": deal_count}


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
