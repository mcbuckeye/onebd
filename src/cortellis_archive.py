"""Lossless response archive for Cortellis expanded deal payloads."""

from __future__ import annotations

import hashlib

from sqlalchemy import text
from sqlalchemy.orm import Session

from .api_client import DealRecord


EXPANDED_ARCHIVE_PARSER_VERSION = 1
_expanded_archive_schema_ready = False


def ensure_expanded_archive_schema(session: Session) -> None:
    """Create the append-only expanded-response archive if needed."""
    global _expanded_archive_schema_ready
    if _expanded_archive_schema_ready:
        return
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS cortellis_expanded_response_history (
            id BIGSERIAL PRIMARY KEY,
            deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
            endpoint VARCHAR(100) NOT NULL,
            response_format VARCHAR(20) NOT NULL,
            response_sha256 CHAR(64) NOT NULL,
            response_body TEXT NOT NULL,
            parser_version INTEGER NOT NULL,
            first_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (deal_id, endpoint, response_sha256)
        )
    """))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_cortellis_expanded_history_deal
        ON cortellis_expanded_response_history (deal_id, last_fetched_at DESC)
    """))
    _expanded_archive_schema_ready = True


def archive_expanded_deal_record(
    session: Session,
    record: DealRecord,
    *,
    endpoint: str,
    parser_version: int = EXPANDED_ARCHIVE_PARSER_VERSION,
) -> str | None:
    """Store an exact response body and return its SHA-256 digest."""
    if not record.raw_xml:
        return None
    ensure_expanded_archive_schema(session)
    response_sha256 = hashlib.sha256(record.raw_xml.encode("utf-8")).hexdigest()
    session.execute(text("""
        INSERT INTO cortellis_expanded_response_history (
            deal_id, endpoint, response_format, response_sha256,
            response_body, parser_version
        ) VALUES (
            :deal_id, :endpoint, 'xml', :response_sha256,
            :response_body, :parser_version
        )
        ON CONFLICT (deal_id, endpoint, response_sha256) DO UPDATE SET
            last_fetched_at = NOW(),
            parser_version = EXCLUDED.parser_version
    """), {
        "deal_id": int(record.id),
        "endpoint": endpoint,
        "response_sha256": response_sha256,
        "response_body": record.raw_xml,
        "parser_version": int(parser_version),
    })
    return response_sha256
