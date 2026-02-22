"""
Unified BD Intelligence Platform - Configuration
"""
import os
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

    # Neo4j Graph Database
    neo4j_uri: str = "bolt://onebd-neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "bdplatform123"

    # Redis
    redis_url: str = "redis://onebd-redis:6379/0"

    # Celery
    broker_url: str = "redis://onebd-redis:6379/0"
    result_backend: str = "redis://onebd-redis:6379/1"

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    embedding_model: str = "text-embedding-3-small"
    vector_dim: int = 1536

    # Cortellis API (for sync)
    cortellis_api_username: str = ""
    cortellis_api_password: str = ""
    cortellis_base_url: str = "https://api.cortellis.com/api-ws/ws/rs"

    # CORS
    allowed_origins: str = "*"

    class Config:
        env_file = ".env.unified"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


# Convenience access
settings = get_settings()
