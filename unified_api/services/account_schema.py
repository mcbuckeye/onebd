"""Durable schema management for user accounts and collaboration features."""

from sqlalchemy import text

from unified_api.services.database import get_cortellis_session


def _apply_account_schema(session) -> None:
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL,
            role VARCHAR(50) NOT NULL DEFAULT 'analyst',
            preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
            disabled BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            last_login TIMESTAMP
        )
    """))
    # Production predates the disabled flag, so CREATE TABLE alone is not a
    # migration for existing installations.
    session.execute(text("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS disabled BOOLEAN NOT NULL DEFAULT FALSE
    """))
    session.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_lower
        ON users(LOWER(email))
    """))
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token VARCHAR(255) UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            used BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_lookup
        ON password_reset_tokens(token, used, expires_at)
    """))


def ensure_account_schema(session=None) -> None:
    """Create or upgrade account tables, optionally within a caller session."""
    if session is not None:
        _apply_account_schema(session)
        session.commit()
        return

    with get_cortellis_session() as managed_session:
        _apply_account_schema(managed_session)
        managed_session.commit()
