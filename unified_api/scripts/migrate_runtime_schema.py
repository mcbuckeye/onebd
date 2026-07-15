"""Apply operational schema migrations before API and worker services start.

OneBD historically created several tables and columns from request and task
paths.  Besides wasting work, concurrent ALTER TABLE statements caused real
PostgreSQL deadlocks.  Docker Compose runs this module as a one-shot service;
the live processes only perform data manipulation after it succeeds.
"""

from sqlalchemy import text

from unified_api.routers.conversations import ensure_conversation_schema
from unified_api.routers.comps import migrate_comp_sets_schema
from unified_api.routers.search import migrate_search_history_schema
from unified_api.services.contract_financial_clauses import (
    ensure_contract_financial_clause_schema,
)
from unified_api.services.account_schema import migrate_account_schema
from unified_api.services.api_credentials import migrate_api_access_schema
from unified_api.services.audit import migrate_audit_schema
from unified_api.services.clinical_trials import ensure_clinical_trials_schema
from unified_api.services.collaboration import migrate_collaboration_schema
from unified_api.services.company_entrant_alerts import (
    ensure_company_entrant_alert_schema,
)
from unified_api.services.cortellis_contract_sync import ensure_contract_scan_schema
from unified_api.services.cortellis_deal_api_sync import migrate_deal_api_scan_schema
from unified_api.services.database import (
    get_cortellis_engine,
    get_cortellis_session,
    get_edgar_source_engine,
)
from unified_api.services.deal_evidence_timeline import ensure_deal_trial_link_schema
from unified_api.services.deal_phase_backfill import ensure_deal_phase_extraction_schema
from unified_api.services.digest_settings import ensure_digest_settings_schema
from unified_api.services.entity_counts import ensure_entity_counts_schema
from unified_api.services.entity_resolution import get_entity_resolution_service
from unified_api.services.europe_pmc_enrichment import ensure_europe_pmc_schema
from unified_api.services.financial_terms import ensure_financial_term_schema
from unified_api.services.operations_telemetry import migrate_operations_schema
from unified_api.services.pubchem_enrichment import ensure_pubchem_schema
from unified_api.services.public_drug_enrichment import ensure_public_drug_schema
from unified_api.services.search_performance import ensure_search_performance_schema
from unified_api.services.sec_company_identity import ensure_sec_company_identity_schema
from unified_api.services.source_monitoring import ensure_source_monitoring_tables
from unified_api.services.uniprot_enrichment import ensure_public_target_schema
from src.cortellis_archive import ensure_expanded_archive_schema
from src.cortellis_catalog import (
    ensure_catalog_exclusion_schema,
    ensure_catalog_proof_schema,
)


MIGRATION_LOCK_ID = 710_062_024


def _apply_runtime_schema_migrations() -> None:
    """Apply all application-owned schemas in dependency order."""
    migrate_account_schema()
    migrate_collaboration_schema()
    migrate_api_access_schema()
    get_entity_resolution_service().migrate_identity_schema()

    ensure_public_drug_schema()
    ensure_pubchem_schema()
    ensure_public_target_schema()
    ensure_europe_pmc_schema()
    ensure_clinical_trials_schema()
    ensure_sec_company_identity_schema()

    with get_cortellis_session() as session:
        ensure_conversation_schema(session)
        migrate_comp_sets_schema(session)
        migrate_search_history_schema(session)
        migrate_audit_schema(session)
        ensure_source_monitoring_tables(session)
        ensure_contract_financial_clause_schema(session)
        ensure_expanded_archive_schema(session)
        ensure_catalog_exclusion_schema(session)
        ensure_catalog_proof_schema(session)
        ensure_entity_counts_schema(session)
        ensure_financial_term_schema(session)
        ensure_deal_phase_extraction_schema(session)
        ensure_digest_settings_schema(session)
        ensure_company_entrant_alert_schema(session)
        ensure_deal_trial_link_schema(session)
        session.commit()

    ensure_contract_scan_schema()
    migrate_deal_api_scan_schema()
    migrate_operations_schema()
    ensure_search_performance_schema()
    with get_edgar_source_engine().connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_stat_statements"))
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        connection.execute(text(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_edgar_companies_name_upper_trgm "
            "ON companies USING gin (UPPER(name) gin_trgm_ops)"
        ))
        connection.execute(text(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_edgar_documents_effective_type_id "
            "ON documents ((COALESCE(subtype, doc_type)), id)"
        ))
        connection.execute(text(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_edgar_raw_documents_company_id "
            "ON raw_documents (company_id, id)"
        ))
        connection.execute(text(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_edgar_documents_raw_document_id "
            "ON documents (raw_document_id, id)"
        ))


def migrate_runtime_schema() -> None:
    """Apply idempotent operational DDL under one deployment-wide lock."""
    with get_cortellis_engine().connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as lock_connection:
        lock_connection.execute(text("SELECT pg_advisory_lock(:lock_id)"), {
            "lock_id": MIGRATION_LOCK_ID,
        })
        try:
            _apply_runtime_schema_migrations()
        finally:
            lock_connection.execute(text(
                "SELECT pg_advisory_unlock(:lock_id)"
            ), {"lock_id": MIGRATION_LOCK_ID})


if __name__ == "__main__":
    migrate_runtime_schema()
