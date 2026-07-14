"""Resumable repair of deal-level phase fields from lossless Cortellis archives."""

from __future__ import annotations

from sqlalchemy import text

from src.deal_phases import derive_deal_phases_from_xml


DEAL_PHASE_PARSER_VERSION = 1


def ensure_deal_phase_extraction_schema(session) -> None:
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS deal_phase_extractions (
            deal_id INTEGER PRIMARY KEY REFERENCES deals(id) ON DELETE CASCADE,
            response_sha256 CHAR(64) NOT NULL,
            parser_version INTEGER NOT NULL,
            phase_highest_start VARCHAR(100),
            phase_highest_now VARCHAR(100),
            status VARCHAR(20) NOT NULL,
            error_message TEXT,
            extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))


def backfill_deal_phase_batch(
    session,
    *,
    batch_size: int = 1000,
    after_deal_id: int = 0,
) -> dict:
    """Repair one archive-backed batch and checkpoint every inspected deal."""
    batch_size = max(1, min(5000, int(batch_size)))
    acquired = session.execute(text(
        "SELECT pg_try_advisory_xact_lock(hashtext('onebd_deal_phase_backfill'))"
    )).scalar()
    if not acquired:
        return {
            "status": "busy",
            "processed": 0,
            "updated": 0,
            "without_phase": 0,
            "errors": 0,
            "last_deal_id": int(after_deal_id),
        }

    ensure_deal_phase_extraction_schema(session)
    rows = session.execute(text("""
        SELECT deal.id AS deal_id,
               archive.response_sha256,
               archive.response_body
        FROM deals deal
        JOIN LATERAL (
            SELECT history.response_sha256, history.response_body
            FROM cortellis_expanded_response_history history
            WHERE history.deal_id = deal.id
            ORDER BY history.last_fetched_at DESC, history.id DESC
            LIMIT 1
        ) archive ON TRUE
        LEFT JOIN deal_phase_extractions extraction
          ON extraction.deal_id = deal.id
        WHERE deal.id > :after_deal_id
          AND (
               extraction.deal_id IS NULL
            OR extraction.parser_version <> :parser_version
            OR extraction.response_sha256 <> archive.response_sha256
          )
        ORDER BY deal.id
        LIMIT :batch_size
    """), {
        "parser_version": DEAL_PHASE_PARSER_VERSION,
        "batch_size": batch_size,
        "after_deal_id": int(after_deal_id),
    }).mappings().all()

    processed = len(rows)
    updated = 0
    without_phase = 0
    errors = 0
    for row in rows:
        deal_id = int(row["deal_id"])
        try:
            phase_start, phase_now = derive_deal_phases_from_xml(
                row["response_body"]
            )
            session.execute(text("""
                UPDATE deals
                SET phase_highest_start = :phase_start,
                    phase_highest_now = :phase_now
                WHERE id = :deal_id
            """), {
                "deal_id": deal_id,
                "phase_start": phase_start,
                "phase_now": phase_now,
            })
            session.execute(text("""
                INSERT INTO deal_phase_extractions (
                    deal_id, response_sha256, parser_version,
                    phase_highest_start, phase_highest_now,
                    status, error_message, extracted_at
                ) VALUES (
                    :deal_id, :response_sha256, :parser_version,
                    :phase_start, :phase_now, 'completed', NULL, NOW()
                )
                ON CONFLICT (deal_id) DO UPDATE SET
                    response_sha256 = EXCLUDED.response_sha256,
                    parser_version = EXCLUDED.parser_version,
                    phase_highest_start = EXCLUDED.phase_highest_start,
                    phase_highest_now = EXCLUDED.phase_highest_now,
                    status = 'completed', error_message = NULL,
                    extracted_at = NOW()
            """), {
                "deal_id": deal_id,
                "response_sha256": row["response_sha256"],
                "parser_version": DEAL_PHASE_PARSER_VERSION,
                "phase_start": phase_start,
                "phase_now": phase_now,
            })
            if phase_start or phase_now:
                updated += 1
            else:
                without_phase += 1
        except Exception as exc:
            errors += 1
            session.execute(text("""
                INSERT INTO deal_phase_extractions (
                    deal_id, response_sha256, parser_version,
                    status, error_message, extracted_at
                ) VALUES (
                    :deal_id, :response_sha256, :parser_version,
                    'failed', :error, NOW()
                )
                ON CONFLICT (deal_id) DO UPDATE SET
                    response_sha256 = EXCLUDED.response_sha256,
                    parser_version = EXCLUDED.parser_version,
                    status = 'failed', error_message = EXCLUDED.error_message,
                    extracted_at = NOW()
            """), {
                "deal_id": deal_id,
                "response_sha256": row["response_sha256"],
                "parser_version": DEAL_PHASE_PARSER_VERSION,
                "error": str(exc)[:2000],
            })

    return {
        "status": "completed",
        "processed": processed,
        "updated": updated,
        "without_phase": without_phase,
        "errors": errors,
        "parser_version": DEAL_PHASE_PARSER_VERSION,
        "last_deal_id": int(rows[-1]["deal_id"])
        if rows else int(after_deal_id),
    }
