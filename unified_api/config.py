"""
Unified BD Intelligence Platform - Configuration
"""
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # App info
    app_name: str = "BD Intelligence Platform"
    app_version: str = "0.1.0"
    debug: bool = False
    log_level: str = "INFO"

    # Cortellis Database
    cortellis_db_url: str = "postgresql://cortellis:changeme@onebd-db-cortellis:5432/cortellis"

    # Edgar Source Database (SEC filings, 3.3M embedded chunks)
    # In consolidated setup, this is the ONLY Edgar database
    # Both environment variables point to the same database for compatibility
    edgar_source_db_url: str = "postgresql://postgres:postgres@onebd-db-edgar:5432/deals"
    edgar_db_url: str = "postgresql://postgres:postgres@onebd-db-edgar:5432/deals"
    edgar_user_agent: str = "OneBD onebd.pchomelab.com admin@pchomelab.com"
    edgar_storage_dir: str = "/app/storage"
    edgar_sync_batch_days: int = 7
    edgar_sync_overlap_days: int = 3
    edgar_sync_max_filings: int = 250
    edgar_recent_days: int = 3
    edgar_recent_max_filings: int = 250
    edgar_sync_embed: bool = True
    edgar_freshness_warn_hours: int = 48
    edgar_freshness_critical_hours: int = 96
    edgar_fulltext_candidate_limit: int = 500

    # Neo4j Graph Database
    neo4j_uri: str = "bolt://onebd-neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "bdplatform123"
    graph_freshness_warn_hours: int = 36
    graph_freshness_critical_hours: int = 72

    # Optional operations notification channels. State transitions are always
    # persisted even when neither delivery channel is configured.
    source_health_webhook_url: str = ""
    source_health_alert_email: str = ""

    # Redis
    redis_url: str = "redis://onebd-redis:6379/0"

    # Celery
    broker_url: str = "redis://onebd-redis:6379/0"
    result_backend: str = "redis://onebd-redis:6379/1"

    # OpenAI - Agentic RAG uses best reasoning model
    openai_api_key: str = ""
    openai_model: str = "gpt-5.3-codex"  # Best for reasoning and tool-driven agents
    embedding_model: str = "text-embedding-3-small"
    vector_dim: int = 1536

    # Cortellis API (for sync)
    cortellis_api_username: str = ""
    cortellis_api_password: str = ""
    cortellis_base_url: str = "https://api.cortellis.com/api-ws/ws/rs"
    cortellis_sync_overlap_days: int = 2
    cortellis_catalog_scan_workers: int = 8
    cortellis_catalog_repair_limit: int = 30000
    cortellis_contract_scan_batch_size: int = 5000
    cortellis_contract_scan_workers: int = 8
    cortellis_deal_api_scan_batch_size: int = 5000
    cortellis_deal_api_scan_workers: int = 8
    cortellis_freshness_warn_hours: int = 36
    cortellis_freshness_critical_hours: int = 72

    # ClinicalTrials.gov API v2 (free public source)
    clinicaltrials_base_url: str = "https://clinicaltrials.gov/api/v2"
    clinicaltrials_user_agent: str = (
        "OneBD onebd.pchomelab.com admin@pchomelab.com"
    )
    clinicaltrials_page_size: int = 500
    clinicaltrials_recent_overlap_days: int = 7
    clinicaltrials_recent_max_pages: int = 10
    clinicaltrials_backfill_window_days: int = 90
    clinicaltrials_backfill_max_pages: int = 50

    # Free public drug/target sources
    public_data_user_agent: str = (
        "OneBD onebd.pchomelab.com admin@pchomelab.com"
    )
    chembl_base_url: str = "https://www.ebi.ac.uk/chembl/api/data"
    chembl_request_interval_seconds: float = 0.2
    open_targets_base_url: str = "https://api.platform.opentargets.org/api/v4"
    open_targets_request_interval_seconds: float = 0.25
    uniprot_base_url: str = "https://rest.uniprot.org"
    uniprot_request_interval_seconds: float = 0.25
    europe_pmc_base_url: str = (
        "https://www.ebi.ac.uk/europepmc/webservices/rest"
    )
    europe_pmc_request_interval_seconds: float = 0.25
    europe_pmc_page_size: int = 100
    gleif_base_url: str = "https://api.gleif.org"
    gleif_request_interval_seconds: float = 0.2
    gleif_refresh_days: int = 30
    wikidata_query_url: str = "https://query.wikidata.org"
    wikidata_request_interval_seconds: float = 0.25
    wikidata_refresh_days: int = 30

    # CORS
    allowed_origins: str = "*"
    app_url: str = "https://onebd.pchomelab.com"

    class Config:
        env_file = ".env.unified"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience access
settings = get_settings()
