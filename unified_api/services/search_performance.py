"""One-time production schema changes supporting advanced-search performance."""

from __future__ import annotations

from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_engine


logger = structlog.get_logger(__name__)
SEARCH_SCHEMA_VERSION = 1
ADVISORY_LOCK_ID = 61320260716


INDEX_STATEMENTS = (
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deal_drugs_drug_deal "
    "ON deal_drugs (drug_id, deal_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deal_companies_company_role_deal "
    "ON deal_companies (company_id, role, deal_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deal_actions_action_type_deal "
    "ON deal_actions (action_id, action_type, deal_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deal_indications_indication_deal "
    "ON deal_indications (indication_id, deal_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deal_technologies_technology_deal "
    "ON deal_technologies (technology_id, deal_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deal_territories_territory_type_deal "
    "ON deal_territories (territory_id, territory_type, deal_id)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deal_timeline_deal_date "
    "ON deal_timeline_events (deal_id, event_date)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_drugs_name_display_trgm "
    "ON drugs USING gin (name_display gin_trgm_ops)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_drug_aliases_alias_value_trgm "
    "ON drug_aliases USING gin (alias_value gin_trgm_ops)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_actions_name_trgm "
    "ON actions USING gin (name gin_trgm_ops)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_indications_name_trgm "
    "ON indications USING gin (name gin_trgm_ops)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_technologies_name_trgm "
    "ON technologies USING gin (name gin_trgm_ops)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deals_title_trgm "
    "ON deals USING gin (title gin_trgm_ops)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deals_summary_trgm "
    "ON deals USING gin (summary gin_trgm_ops)",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deals_deal_type_lower "
    "ON deals (LOWER(deal_type))",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deals_agreement_type_lower "
    "ON deals (LOWER(agreement_type))",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deals_transaction_type_lower "
    "ON deals (LOWER(transaction_type))",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deals_status_lower "
    "ON deals (LOWER(status))",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_deals_phase_now_lower "
    "ON deals (LOWER(phase_highest_now))",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_drugs_name_display_lower "
    "ON drugs (LOWER(name_display))",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_drug_aliases_alias_value_lower "
    "ON drug_aliases (LOWER(alias_value))",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_actions_name_lower "
    "ON actions (LOWER(name))",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_indications_name_lower "
    "ON indications (LOWER(name))",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_technologies_name_lower "
    "ON technologies (LOWER(name))",
    "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_companies_name_lower "
    "ON companies (LOWER(name))",
)


def ensure_search_performance_schema() -> None:
    """Install indexes once, serialized across multiple Uvicorn workers."""
    engine = get_cortellis_engine()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        # Do not let the other Uvicorn workers wait on this session lock.
        # CREATE INDEX CONCURRENTLY waits for older transactions, so blocking
        # startup workers here can otherwise form a PostgreSQL deadlock cycle.
        acquired = bool(
            conn.execute(
                text("SELECT pg_try_advisory_lock(:lock_id)"),
                {"lock_id": ADVISORY_LOCK_ID},
            ).scalar()
        )
        if not acquired:
            logger.info("search_performance_schema_owned_by_another_worker")
            return
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_stat_statements"))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS search_performance_schema_versions (
                    version INTEGER PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))
            applied = conn.execute(
                text("""
                    SELECT 1 FROM search_performance_schema_versions
                    WHERE version=:version
                """),
                {"version": SEARCH_SCHEMA_VERSION},
            ).first()
            if applied:
                return
            for statement in INDEX_STATEMENTS:
                conn.execute(text(statement))
            for table in (
                "deals",
                "drugs",
                "deal_drugs",
                "deal_companies",
                "deal_actions",
                "deal_indications",
                "deal_technologies",
                "deal_territories",
                "drug_aliases",
            ):
                conn.execute(text(f"ANALYZE {table}"))
            conn.execute(
                text("""
                    INSERT INTO search_performance_schema_versions (version)
                    VALUES (:version) ON CONFLICT (version) DO NOTHING
                """),
                {"version": SEARCH_SCHEMA_VERSION},
            )
            logger.info(
                "search_performance_schema_applied",
                version=SEARCH_SCHEMA_VERSION,
                indexes=len(INDEX_STATEMENTS),
            )
        finally:
            conn.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": ADVISORY_LOCK_ID},
            )
