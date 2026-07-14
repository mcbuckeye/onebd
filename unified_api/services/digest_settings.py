"""Shared schema initialization for scheduled digest preferences."""

from sqlalchemy import text


def ensure_digest_settings_schema(session) -> None:
    """Create or safely extend the per-user digest settings table."""
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS user_digest_settings (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL UNIQUE,
            enabled BOOLEAN DEFAULT FALSE,
            frequency VARCHAR(20) DEFAULT 'weekly',
            therapy_areas JSONB DEFAULT '[]',
            company_ids JSONB DEFAULT '[]',
            email VARCHAR(255),
            include_catalysts BOOLEAN NOT NULL DEFAULT TRUE,
            catalyst_days INTEGER NOT NULL DEFAULT 30,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """))
    session.execute(text("""
        ALTER TABLE user_digest_settings
        ADD COLUMN IF NOT EXISTS include_catalysts BOOLEAN NOT NULL DEFAULT TRUE
    """))
    session.execute(text("""
        ALTER TABLE user_digest_settings
        ADD COLUMN IF NOT EXISTS catalyst_days INTEGER NOT NULL DEFAULT 30
    """))
