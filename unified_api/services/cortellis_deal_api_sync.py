"""Durable lossless Cortellis deal-response and source-citation scanner."""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
import threading
from typing import Any

from sqlalchemy import text

from src.api_client import CortellisClient, DealRecord, DealSourcesRecord
from src.cortellis_catalog import (
    ensure_catalog_exclusion_schema,
    read_catalog_proof,
)
from src.config import CortellisConfig
from src.cortellis_archive import archive_expanded_deal_record
from src.deal_phases import derive_deal_phases
from unified_api.config import settings
from unified_api.services.database import (
    get_cortellis_engine,
    get_cortellis_session,
)


DEAL_API_SCAN_VERSION = 1
SINGLE_DEAL_ENDPOINT = "deals-v2/deal/expanded/{id}"
DEAL_SOURCES_ENDPOINT = "deals-v2/deal/sources/{dealId}"
_deal_api_scan_schema_ready = False
_deal_api_scan_schema_lock = threading.Lock()


def migrate_deal_api_scan_schema() -> None:
    """Create durable response, citation, and checkpoint tables at deploy time."""
    global _deal_api_scan_schema_ready
    if _deal_api_scan_schema_ready:
        return
    with get_cortellis_session() as session:
        # The helper creates the shared append-only expanded response table in
        # the same committed schema transaction.
        from src.cortellis_archive import ensure_expanded_archive_schema

        ensure_expanded_archive_schema(session)
        ensure_catalog_exclusion_schema(session)
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS cortellis_deal_source_response_history (
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
            CREATE INDEX IF NOT EXISTS ix_cortellis_source_history_deal
            ON cortellis_deal_source_response_history (
                deal_id, last_fetched_at DESC
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS cortellis_deal_sources (
                deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
                source_id VARCHAR(100) NOT NULL,
                source_type VARCHAR(100) NOT NULL DEFAULT '',
                is_current BOOLEAN NOT NULL DEFAULT TRUE,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (deal_id, source_id, source_type)
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_cortellis_deal_sources_source
            ON cortellis_deal_sources (source_id, source_type)
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS cortellis_deal_api_scan_state (
                deal_id INTEGER PRIMARY KEY REFERENCES deals(id) ON DELETE CASCADE,
                scanner_version INTEGER NOT NULL,
                status VARCHAR(20) NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                expanded_response_sha256 CHAR(64),
                source_response_sha256 CHAR(64),
                source_count INTEGER,
                last_error TEXT,
                last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                next_retry_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_cortellis_deal_api_scan_retry
            ON cortellis_deal_api_scan_state (
                scanner_version, status, next_retry_at, deal_id
            )
        """))
    _deal_api_scan_schema_ready = True


def ensure_deal_api_scan_schema() -> None:
    """Verify the deal-response migration once per application process."""
    global _deal_api_scan_schema_ready
    if _deal_api_scan_schema_ready:
        return
    with _deal_api_scan_schema_lock:
        if _deal_api_scan_schema_ready:
            return
        with get_cortellis_session() as session:
            installed = session.execute(text(
                "SELECT to_regclass('public.cortellis_deal_api_scan_state') "
                "IS NOT NULL"
            )).scalar()
        if not installed:
            raise RuntimeError(
                "Cortellis deal API scan schema is missing; run the runtime "
                "schema migration"
            )
        _deal_api_scan_schema_ready = True


def _claim_candidates(batch_size: int) -> list[int]:
    batch_size = max(1, min(5000, int(batch_size)))
    with get_cortellis_session() as session:
        rows = session.execute(text("""
            WITH candidates AS (
                SELECT deal.id
                FROM deals deal
                LEFT JOIN cortellis_deal_api_scan_state state
                  ON state.deal_id = deal.id
                LEFT JOIN cortellis_catalog_exclusions exclusion
                  ON exclusion.deal_id = deal.id
                WHERE exclusion.deal_id IS NULL
                  AND (
                       state.deal_id IS NULL
                    OR state.scanner_version <> :scanner_version
                    OR (
                        state.status = 'failed'
                        AND state.attempts < 3
                        AND state.next_retry_at <= NOW()
                    )
                    OR (
                        state.status = 'in_progress'
                        AND state.last_attempt_at < NOW() - INTERVAL '1 hour'
                    )
                  )
                ORDER BY
                    CASE WHEN state.deal_id IS NULL THEN 0 ELSE 1 END,
                    deal.id
                LIMIT :batch_size
                FOR UPDATE OF deal SKIP LOCKED
            )
            INSERT INTO cortellis_deal_api_scan_state (
                deal_id, scanner_version, status, attempts,
                expanded_response_sha256, source_response_sha256,
                source_count, last_error, last_attempt_at,
                next_retry_at, completed_at
            )
            SELECT id, :scanner_version, 'in_progress', 1,
                   NULL, NULL, NULL, NULL, NOW(), NULL, NULL
            FROM candidates
            ON CONFLICT (deal_id) DO UPDATE SET
                scanner_version = EXCLUDED.scanner_version,
                status = 'in_progress',
                attempts = CASE
                    WHEN cortellis_deal_api_scan_state.scanner_version =
                         EXCLUDED.scanner_version
                    THEN cortellis_deal_api_scan_state.attempts + 1
                    ELSE 1
                END,
                expanded_response_sha256 = NULL,
                source_response_sha256 = NULL,
                source_count = NULL,
                last_error = NULL,
                last_attempt_at = NOW(),
                next_retry_at = NULL,
                completed_at = NULL
            RETURNING deal_id
        """), {
            "scanner_version": DEAL_API_SCAN_VERSION,
            "batch_size": batch_size,
        }).scalars().all()
    return [int(deal_id) for deal_id in rows]


def _validate_expanded_record(deal_id: int, record: DealRecord) -> None:
    if int(record.id) != int(deal_id):
        raise ValueError(
            f"Expanded response returned deal {record.id} for requested {deal_id}"
        )
    attributes = record.parsed_data.get("@attributes", {})
    response_id = attributes.get("id") if isinstance(attributes, dict) else None
    if response_id is None or int(response_id) != int(deal_id):
        raise ValueError(
            f"Expanded response for deal {deal_id} omitted or mismatched root ID"
        )
    if not record.raw_xml:
        raise ValueError(f"Expanded response for deal {deal_id} was empty")


def _archive_source_response(
    session,
    sources_record: DealSourcesRecord,
) -> str:
    raw_response = sources_record.raw_response
    if not raw_response:
        raise ValueError(
            f"Source response for deal {sources_record.deal_id} was empty"
        )
    response_sha256 = hashlib.sha256(raw_response.encode("utf-8")).hexdigest()
    session.execute(text("""
        INSERT INTO cortellis_deal_source_response_history (
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
        "deal_id": int(sources_record.deal_id),
        "endpoint": DEAL_SOURCES_ENDPOINT,
        "response_sha256": response_sha256,
        "response_body": raw_response,
        "parser_version": DEAL_API_SCAN_VERSION,
    })
    return response_sha256


def _record_success(
    deal_id: int,
    expanded_record: DealRecord,
    sources_record: DealSourcesRecord,
) -> None:
    _validate_expanded_record(deal_id, expanded_record)
    if int(sources_record.deal_id) != int(deal_id):
        raise ValueError(
            f"Source response returned deal {sources_record.deal_id} "
            f"for requested {deal_id}"
        )
    with get_cortellis_session() as session:
        expanded_sha256 = archive_expanded_deal_record(
            session,
            expanded_record,
            endpoint=SINGLE_DEAL_ENDPOINT,
            parser_version=DEAL_API_SCAN_VERSION,
        )
        if not expanded_sha256:
            raise ValueError(f"Expanded response for deal {deal_id} was empty")
        phase_start, phase_now = derive_deal_phases(expanded_record.parsed_data)
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
        source_sha256 = _archive_source_response(session, sources_record)
        session.execute(text("""
            UPDATE cortellis_deal_sources
            SET is_current = FALSE
            WHERE deal_id = :deal_id
        """), {"deal_id": deal_id})
        for source in sources_record.sources:
            session.execute(text("""
                INSERT INTO cortellis_deal_sources (
                    deal_id, source_id, source_type, is_current
                ) VALUES (
                    :deal_id, :source_id, :source_type, TRUE
                )
                ON CONFLICT (deal_id, source_id, source_type) DO UPDATE SET
                    is_current = TRUE,
                    last_seen_at = NOW()
            """), {
                "deal_id": deal_id,
                "source_id": source.source_id,
                "source_type": source.source_type,
            })
        session.execute(text("""
            UPDATE cortellis_deal_api_scan_state
            SET status = 'completed',
                expanded_response_sha256 = :expanded_sha256,
                source_response_sha256 = :source_sha256,
                source_count = :source_count,
                last_error = NULL,
                next_retry_at = NULL,
                completed_at = NOW()
            WHERE deal_id = :deal_id
              AND scanner_version = :scanner_version
        """), {
            "deal_id": deal_id,
            "scanner_version": DEAL_API_SCAN_VERSION,
            "expanded_sha256": expanded_sha256,
            "source_sha256": source_sha256,
            "source_count": len(sources_record.sources),
        })


def _record_failure(deal_id: int, error: Exception) -> None:
    with get_cortellis_session() as session:
        session.execute(text("""
            UPDATE cortellis_deal_api_scan_state
            SET status = 'failed',
                last_error = :error,
                next_retry_at = NOW() + INTERVAL '15 minutes' *
                    POWER(2, LEAST(GREATEST(attempts - 1, 0), 5))
            WHERE deal_id = :deal_id
              AND scanner_version = :scanner_version
        """), {
            "deal_id": deal_id,
            "scanner_version": DEAL_API_SCAN_VERSION,
            "error": str(error)[:4000],
        })


def _scan_chunk(deal_ids: list[int]) -> list[dict[str, Any]]:
    config = CortellisConfig(
        username=settings.cortellis_api_username,
        password=settings.cortellis_api_password,
        base_url=settings.cortellis_base_url,
    )
    outcomes: list[dict[str, Any]] = []
    with CortellisClient(config) as client:
        for deal_id in deal_ids:
            try:
                expanded = client.get_deal_record(deal_id)
                sources = client.get_deal_sources(deal_id)
                _record_success(deal_id, expanded, sources)
                outcomes.append({
                    "deal_id": deal_id,
                    "status": "completed",
                    "sources": len(sources.sources),
                })
            except Exception as exc:
                _record_failure(deal_id, exc)
                outcomes.append({
                    "deal_id": deal_id,
                    "status": "failed",
                    "sources": 0,
                    "error": str(exc)[:500],
                })
    return outcomes


def deal_api_scan_status() -> dict[str, Any]:
    """Report lossless-response and source-citation coverage."""
    ensure_deal_api_scan_schema()
    with get_cortellis_session() as session:
        row = session.execute(text("""
            SELECT
                (SELECT COUNT(*)
                 FROM deals deal
                 WHERE NOT EXISTS (
                     SELECT 1 FROM cortellis_catalog_exclusions exclusion
                     WHERE exclusion.deal_id = deal.id
                 )) AS eligible_deals,
                COUNT(*) FILTER (
                    WHERE state.scanner_version = :scanner_version
                      AND state.status = 'completed'
                ) AS completed_deals,
                COUNT(*) FILTER (
                    WHERE state.scanner_version = :scanner_version
                      AND state.status = 'in_progress'
                ) AS in_progress_deals,
                COUNT(*) FILTER (
                    WHERE state.scanner_version = :scanner_version
                      AND state.status = 'failed'
                      AND state.attempts < 3
                ) AS retryable_failures,
                COUNT(*) FILTER (
                    WHERE state.scanner_version = :scanner_version
                      AND state.status = 'failed'
                      AND state.attempts >= 3
                ) AS terminal_failures,
                (SELECT COUNT(DISTINCT history.deal_id)
                 FROM cortellis_expanded_response_history history
                 WHERE history.endpoint = :single_endpoint
                   AND NOT EXISTS (
                       SELECT 1 FROM cortellis_catalog_exclusions exclusion
                       WHERE exclusion.deal_id = history.deal_id
                   )) AS exact_raw_deals,
                (SELECT COUNT(*)
                 FROM cortellis_expanded_response_history) AS raw_versions,
                (SELECT COUNT(DISTINCT history.deal_id)
                 FROM cortellis_deal_source_response_history history
                 WHERE NOT EXISTS (
                     SELECT 1 FROM cortellis_catalog_exclusions exclusion
                     WHERE exclusion.deal_id = history.deal_id
                 )) AS source_raw_deals,
                (SELECT COUNT(*)
                 FROM cortellis_deal_source_response_history) AS source_versions,
                (SELECT COUNT(*) FROM cortellis_deal_sources source
                 WHERE source.is_current
                   AND NOT EXISTS (
                       SELECT 1 FROM cortellis_catalog_exclusions exclusion
                       WHERE exclusion.deal_id = source.deal_id
                   )) AS current_source_references
            FROM cortellis_deal_api_scan_state state
            WHERE NOT EXISTS (
                SELECT 1 FROM cortellis_catalog_exclusions exclusion
                WHERE exclusion.deal_id = state.deal_id
            )
        """), {
            "scanner_version": DEAL_API_SCAN_VERSION,
            "single_endpoint": SINGLE_DEAL_ENDPOINT,
        }).mappings().one()
    result = dict(row)
    eligible = int(result["eligible_deals"] or 0)
    completed = int(result["completed_deals"] or 0)
    known_current = sum(int(result[key] or 0) for key in (
        "completed_deals",
        "in_progress_deals",
        "retryable_failures",
        "terminal_failures",
    ))
    result["scanner_version"] = DEAL_API_SCAN_VERSION
    result["unattempted_deals"] = max(0, eligible - known_current)
    result["remaining_deals"] = max(0, eligible - completed)
    result["coverage_pct"] = round(100 * completed / eligible, 2) if eligible else 0.0
    result["coverage_complete"] = bool(
        eligible > 0
        and completed == eligible
        and int(result["exact_raw_deals"] or 0) == eligible
        and int(result["source_raw_deals"] or 0) == eligible
        and not result["terminal_failures"]
    )
    return result


def _latest_catalog_proof() -> dict[str, Any]:
    """Read the most recent successful exhaustive membership result."""
    with get_cortellis_session() as session:
        proof = read_catalog_proof(session)
    if proof:
        proof["last_success_at"] = proof.get("verified_at")
    return proof


def _effective_catalog_total(proof: dict[str, Any]) -> int | None:
    """Return the exhaustive baseline plus proven incremental additions."""
    value = proof.get("effective_retrievable_total")
    if value is None:
        value = proof.get("retrievable_total")
    return int(value) if value is not None else None


def _attach_catalog_cardinality(result: dict[str, Any]) -> dict[str, Any]:
    """Require both full response coverage and a successful exhaustive audit."""
    config = CortellisConfig(
        username=settings.cortellis_api_username,
        password=settings.cortellis_api_password,
        base_url=settings.cortellis_base_url,
    )
    try:
        with CortellisClient(config) as client:
            catalog_total = client.search_deals(
                query="*", offset=0, hits=1
            ).total_results
        catalog_proof = _latest_catalog_proof()
        retrievable_total = _effective_catalog_total(catalog_proof)
        verified_at = catalog_proof.get("last_success_at")
        result["catalog_total"] = catalog_total
        result["verified_retrievable_total"] = retrievable_total
        result["exhaustive_retrievable_total"] = catalog_proof.get(
            "retrievable_total"
        )
        result["incremental_retrievable_additions"] = catalog_proof.get(
            "incremental_retrievable_additions", 0
        )
        result["catalog_verified_at"] = (
            verified_at.isoformat()
            if hasattr(verified_at, "isoformat")
            else verified_at
        )
        result["catalog_membership_complete"] = bool(
            result.get("coverage_complete")
            and retrievable_total is not None
            and int(result.get("eligible_deals") or 0) == int(retrievable_total)
        )
    except Exception as exc:
        result["catalog_total"] = None
        result["catalog_membership_complete"] = False
        result["catalog_probe_error"] = str(exc)[:500]
    return result


def sync_deal_api_coverage_batch(
    *,
    batch_size: int = 500,
    workers: int = 5,
) -> dict[str, Any]:
    """Fetch one resumable batch of exact deal and source responses."""
    ensure_deal_api_scan_schema()
    engine = get_cortellis_engine()
    lock_connection = engine.connect()
    acquired = bool(lock_connection.execute(text(
        "SELECT pg_try_advisory_lock(hashtext('onebd_cortellis_deal_api_scan'))"
    )).scalar())
    if not acquired:
        lock_connection.close()
        return {
            "status": "skipped",
            "reason": "deal API coverage scan already running",
            **deal_api_scan_status(),
        }

    try:
        candidates = _claim_candidates(batch_size)
        if not candidates:
            status = deal_api_scan_status()
            run_status = "partial" if status["terminal_failures"] else "completed"
            return _attach_catalog_cardinality({
                "status": run_status,
                "processed": 0,
                **status,
            })

        workers = max(1, min(int(workers), 8, len(candidates)))
        chunks = [candidates[index::workers] for index in range(workers)]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            nested_outcomes = list(executor.map(_scan_chunk, chunks))
        outcomes = [outcome for chunk in nested_outcomes for outcome in chunk]
        completed = sum(item["status"] == "completed" for item in outcomes)
        failed = len(outcomes) - completed
        status = deal_api_scan_status()
        result = {
            "status": "partial" if failed else "completed",
            "processed": len(outcomes),
            "completed": completed,
            "failed": failed,
            "sources_observed": sum(int(item["sources"]) for item in outcomes),
            **status,
        }
        failures = [item for item in outcomes if item["status"] == "failed"]
        if failures:
            result["error"] = "; ".join(
                f"deal {item['deal_id']}: {item['error']}" for item in failures[:10]
            )
        return _attach_catalog_cardinality(result)
    finally:
        try:
            lock_connection.execute(text(
                "SELECT pg_advisory_unlock(hashtext('onebd_cortellis_deal_api_scan'))"
            ))
        finally:
            lock_connection.close()
