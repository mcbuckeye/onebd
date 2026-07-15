"""Durable schema management for user accounts and collaboration features."""

import threading

from sqlalchemy import text

from unified_api.services.database import get_cortellis_session


_schema_ready = False
_schema_lock = threading.Lock()


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


def migrate_account_schema(session=None) -> None:
    """Create or upgrade account tables during deployment."""
    global _schema_ready
    if session is not None:
        _apply_account_schema(session)
        session.commit()
        _schema_ready = True
        return

    with get_cortellis_session() as managed_session:
        _apply_account_schema(managed_session)
        managed_session.commit()
    _schema_ready = True


def ensure_account_schema(session=None) -> None:
    """Verify the account migration once per application process."""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        if session is not None:
            installed = session.execute(
                text("SELECT to_regclass('public.users') IS NOT NULL")
            ).scalar()
        else:
            with get_cortellis_session() as managed_session:
                installed = managed_session.execute(
                    text("SELECT to_regclass('public.users') IS NOT NULL")
                ).scalar()
        if not installed:
            raise RuntimeError(
                "Account schema is missing; run the runtime schema migration"
            )
        _schema_ready = True
