"""Durable, bounded coverage scan for Cortellis contract metadata."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from sqlalchemy import text

from src.api_client import CortellisClient
from src.config import CortellisConfig
from unified_api.config import settings
from unified_api.services.database import (
    get_cortellis_engine,
    get_cortellis_session,
)


CONTRACT_SCAN_VERSION = 1
_contract_scan_schema_ready = False


def ensure_contract_scan_schema() -> None:
    """Create the per-deal checkpoint used across deploys and worker restarts."""
    global _contract_scan_schema_ready
    if _contract_scan_schema_ready:
        return
    with get_cortellis_session() as session:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS cortellis_contract_scan_state (
                deal_id INTEGER PRIMARY KEY REFERENCES deals(id) ON DELETE CASCADE,
                scanner_version INTEGER NOT NULL,
                status VARCHAR(20) NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                contract_count INTEGER,
                last_error TEXT,
                last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                next_retry_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_cortellis_contract_scan_retry
            ON cortellis_contract_scan_state (
                scanner_version, status, next_retry_at, deal_id
            )
        """))
    _contract_scan_schema_ready = True


def _claim_candidates(batch_size: int) -> list[int]:
    batch_size = max(1, min(5000, int(batch_size)))
    with get_cortellis_session() as session:
        rows = session.execute(text("""
            WITH candidates AS (
                SELECT deal.id
                FROM deals deal
                LEFT JOIN cortellis_contract_scan_state state
                  ON state.deal_id = deal.id
                WHERE state.deal_id IS NULL
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
                ORDER BY
                    CASE WHEN state.deal_id IS NULL THEN 0 ELSE 1 END,
                    deal.id
                LIMIT :batch_size
                FOR UPDATE OF deal SKIP LOCKED
            )
            INSERT INTO cortellis_contract_scan_state (
                deal_id, scanner_version, status, attempts, contract_count,
                last_error, last_attempt_at, next_retry_at, completed_at
            )
            SELECT id, :scanner_version, 'in_progress', 1, NULL,
                   NULL, NOW(), NULL, NULL
            FROM candidates
            ON CONFLICT (deal_id) DO UPDATE SET
                scanner_version = EXCLUDED.scanner_version,
                status = 'in_progress',
                attempts = CASE
                    WHEN cortellis_contract_scan_state.scanner_version =
                         EXCLUDED.scanner_version
                    THEN cortellis_contract_scan_state.attempts + 1
                    ELSE 1
                END,
                contract_count = NULL,
                last_error = NULL,
                last_attempt_at = NOW(),
                next_retry_at = NULL,
                completed_at = NULL
            RETURNING deal_id
        """), {
            "scanner_version": CONTRACT_SCAN_VERSION,
            "batch_size": batch_size,
        }).scalars().all()
    return [int(deal_id) for deal_id in rows]


def _parse_contract_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d")


def _record_success(deal_id: int, contracts: list[dict[str, Any]]) -> None:
    with get_cortellis_session() as session:
        for contract in contracts:
            contract_id = int(contract.get("id") or 0)
            if contract_id <= 0:
                raise ValueError(f"Contract response for deal {deal_id} omitted its ID")
            contract_types = contract.get("types") or []
            if isinstance(contract_types, str):
                contract_types = [contract_types]
            session.execute(text("""
                INSERT INTO deal_contracts (
                    id, deal_id, contract_types, has_pdf, has_text,
                    date_filing, date_contract, is_redacted
                ) VALUES (
                    :id, :deal_id, :contract_types, :has_pdf, :has_text,
                    :date_filing, :date_contract, :is_redacted
                )
                ON CONFLICT (id) DO UPDATE SET
                    deal_id = EXCLUDED.deal_id,
                    contract_types = EXCLUDED.contract_types,
                    has_pdf = EXCLUDED.has_pdf,
                    has_text = EXCLUDED.has_text,
                    date_filing = EXCLUDED.date_filing,
                    date_contract = EXCLUDED.date_contract,
                    is_redacted = EXCLUDED.is_redacted
            """), {
                "id": contract_id,
                "deal_id": deal_id,
                "contract_types": ",".join(str(value) for value in contract_types),
                "has_pdf": bool(contract.get("has_pdf")),
                "has_text": bool(contract.get("has_text")),
                "date_filing": _parse_contract_date(contract.get("date_filing")),
                "date_contract": _parse_contract_date(contract.get("date_contract")),
                "is_redacted": bool(contract.get("is_redacted")),
            })
        session.execute(text("""
            UPDATE deals
            SET has_contract = :has_contract
            WHERE id = :deal_id
        """), {"deal_id": deal_id, "has_contract": bool(contracts)})
        session.execute(text("""
            UPDATE cortellis_contract_scan_state
            SET status = 'completed',
                contract_count = :contract_count,
                last_error = NULL,
                next_retry_at = NULL,
                completed_at = NOW()
            WHERE deal_id = :deal_id
              AND scanner_version = :scanner_version
        """), {
            "deal_id": deal_id,
            "scanner_version": CONTRACT_SCAN_VERSION,
            "contract_count": len(contracts),
        })


def _record_failure(deal_id: int, error: Exception) -> None:
    with get_cortellis_session() as session:
        session.execute(text("""
            UPDATE cortellis_contract_scan_state
            SET status = 'failed',
                last_error = :error,
                next_retry_at = NOW() + INTERVAL '15 minutes' *
                    POWER(2, LEAST(GREATEST(attempts - 1, 0), 5))
            WHERE deal_id = :deal_id
              AND scanner_version = :scanner_version
        """), {
            "deal_id": deal_id,
            "scanner_version": CONTRACT_SCAN_VERSION,
            "error": str(error)[:4000],
        })


def _scan_chunk(deal_ids: list[int]) -> list[dict[str, Any]]:
    config = CortellisConfig(
        username=settings.cortellis_api_username,
        password=settings.cortellis_api_password,
        base_url=settings.cortellis_base_url,
    )
    outcomes = []
    with CortellisClient(config) as client:
        for deal_id in deal_ids:
            try:
                contracts = client.get_deal_contracts(deal_id)
                _record_success(deal_id, contracts)
                outcomes.append({
                    "deal_id": deal_id,
                    "status": "completed",
                    "contracts": len(contracts),
                })
            except Exception as exc:
                _record_failure(deal_id, exc)
                outcomes.append({
                    "deal_id": deal_id,
                    "status": "failed",
                    "contracts": 0,
                    "error": str(exc)[:500],
                })
    return outcomes


def contract_scan_status() -> dict[str, Any]:
    """Report coverage from the current scanner version only."""
    ensure_contract_scan_schema()
    with get_cortellis_session() as session:
        row = session.execute(text("""
            SELECT
                (SELECT COUNT(*) FROM deals) AS eligible_deals,
                COUNT(*) FILTER (
                    WHERE state.scanner_version = :scanner_version
                      AND state.status = 'completed'
                ) AS completed_deals,
                COUNT(*) FILTER (
                    WHERE state.scanner_version = :scanner_version
                      AND state.status = 'completed'
                      AND state.contract_count > 0
                ) AS deals_with_contracts,
                COUNT(*) FILTER (
                    WHERE state.scanner_version = :scanner_version
                      AND state.status = 'completed'
                      AND state.contract_count = 0
                ) AS deals_without_contracts,
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
                (SELECT COUNT(*) FROM deal_contracts) AS contract_records,
                (SELECT COUNT(*) FROM deal_contracts WHERE has_pdf) AS pdf_advertised,
                (SELECT COUNT(*) FROM deal_contracts
                 WHERE has_pdf AND pdf_file_path IS NOT NULL) AS pdf_paths_recorded,
                (SELECT COUNT(*) FROM deal_contracts WHERE has_text) AS text_advertised,
                (SELECT COUNT(*) FROM deal_contracts
                 WHERE has_text AND text_file_path IS NOT NULL) AS text_paths_recorded
            FROM cortellis_contract_scan_state state
        """), {"scanner_version": CONTRACT_SCAN_VERSION}).mappings().one()
    result = dict(row)
    eligible = int(result["eligible_deals"] or 0)
    completed = int(result["completed_deals"] or 0)
    known_current = sum(int(result[key] or 0) for key in (
        "completed_deals",
        "in_progress_deals",
        "retryable_failures",
        "terminal_failures",
    ))
    result["scanner_version"] = CONTRACT_SCAN_VERSION
    result["unattempted_deals"] = max(0, eligible - known_current)
    result["remaining_deals"] = max(0, eligible - completed)
    result["coverage_pct"] = round(100 * completed / eligible, 2) if eligible else 0.0
    result["coverage_complete"] = bool(
        eligible > 0
        and completed == eligible
        and not result["terminal_failures"]
    )
    return result


def sync_contract_metadata_batch(
    *,
    batch_size: int = 1000,
    workers: int = 5,
) -> dict[str, Any]:
    """Scan one resumable batch without allowing overlapping workers."""
    ensure_contract_scan_schema()
    engine = get_cortellis_engine()
    lock_connection = engine.connect()
    acquired = bool(lock_connection.execute(text(
        "SELECT pg_try_advisory_lock(hashtext('onebd_cortellis_contract_scan'))"
    )).scalar())
    if not acquired:
        lock_connection.close()
        return {
            "status": "skipped",
            "reason": "contract metadata scan already running",
            **contract_scan_status(),
        }

    try:
        candidates = _claim_candidates(batch_size)
        if not candidates:
            status = contract_scan_status()
            run_status = "partial" if status["terminal_failures"] else "completed"
            return {"status": run_status, "processed": 0, **status}

        workers = max(1, min(int(workers), 8, len(candidates)))
        chunks = [candidates[index::workers] for index in range(workers)]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            nested_outcomes = list(executor.map(_scan_chunk, chunks))
        outcomes = [outcome for chunk in nested_outcomes for outcome in chunk]
        completed = sum(item["status"] == "completed" for item in outcomes)
        failed = len(outcomes) - completed
        status = contract_scan_status()
        result = {
            "status": "partial" if failed else "completed",
            "processed": len(outcomes),
            "completed": completed,
            "failed": failed,
            "contracts_observed": sum(int(item["contracts"]) for item in outcomes),
            **status,
        }
        failures = [item for item in outcomes if item["status"] == "failed"]
        if failures:
            result["error"] = "; ".join(
                f"deal {item['deal_id']}: {item['error']}" for item in failures[:10]
            )
        return result
    finally:
        try:
            lock_connection.execute(text(
                "SELECT pg_advisory_unlock(hashtext('onebd_cortellis_contract_scan'))"
            ))
        finally:
            lock_connection.close()
