"""Persistent state and deduplicated alerts for scheduled source jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Mapping
from urllib.request import Request, urlopen

from sqlalchemy import text
import structlog

from unified_api.config import settings
from unified_api.services.database import get_cortellis_session

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class SourcePolicy:
    label: str
    warn_hours: float
    critical_hours: float


SOURCE_POLICIES = {
    "cortellis": SourcePolicy(
        "Cortellis Sync",
        settings.cortellis_freshness_warn_hours,
        settings.cortellis_freshness_critical_hours,
    ),
    "cortellis_catalog": SourcePolicy(
        "Cortellis Catalog Reconciliation",
        24 * 8,
        24 * 14,
    ),
    "cortellis_contracts": SourcePolicy(
        "Cortellis Contract Metadata Scan",
        1,
        3,
    ),
    "cortellis_deal_api": SourcePolicy(
        "Cortellis Raw Response and Source Scan",
        1,
        3,
    ),
    "edgar_recent": SourcePolicy(
        "EDGAR Recent Sync",
        settings.edgar_freshness_warn_hours,
        settings.edgar_freshness_critical_hours,
    ),
    "edgar_backfill": SourcePolicy(
        "EDGAR Backfill Sync",
        settings.edgar_freshness_warn_hours,
        settings.edgar_freshness_critical_hours,
    ),
    "sec_company_identity": SourcePolicy(
        "SEC Company Identity Audit",
        36,
        72,
    ),
    "gleif_company_identity": SourcePolicy(
        "GLEIF Company Identity Enrichment",
        2,
        6,
    ),
    "gleif_company_ownership": SourcePolicy(
        "GLEIF Company Ownership Enrichment",
        2,
        6,
    ),
    "wikidata_company_domain": SourcePolicy(
        "Wikidata Company Domain Enrichment",
        2,
        6,
    ),
    "clinicaltrials_recent": SourcePolicy(
        "ClinicalTrials.gov Recent Sync",
        36,
        72,
    ),
    "clinicaltrials_backfill": SourcePolicy(
        "ClinicalTrials.gov Historical Backfill",
        2,
        6,
    ),
    "chembl": SourcePolicy(
        "ChEMBL Exact Identifier Enrichment",
        6,
        12,
    ),
    "open_targets": SourcePolicy(
        "Open Targets Drug/Target Enrichment",
        6,
        12,
    ),
    "uniprot": SourcePolicy(
        "UniProt Target Enrichment",
        6,
        12,
    ),
    "europe_pmc": SourcePolicy(
        "Europe PMC Target Literature Enrichment",
        6,
        12,
    ),
    "neo4j": SourcePolicy(
        "Neo4j Graph Sync",
        settings.graph_freshness_warn_hours,
        settings.graph_freshness_critical_hours,
    ),
}


def ensure_source_monitoring_tables(session) -> None:
    """Create the operational schema during the deployment migration phase."""
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS source_job_state (
            source_key VARCHAR(50) PRIMARY KEY,
            label VARCHAR(100) NOT NULL,
            status VARCHAR(20) NOT NULL,
            last_started_at TIMESTAMPTZ,
            last_completed_at TIMESTAMPTZ,
            last_success_at TIMESTAMPTZ,
            consecutive_failures INTEGER NOT NULL DEFAULT 0,
            retry_count INTEGER NOT NULL DEFAULT 0,
            next_retry_at TIMESTAMPTZ,
            last_error TEXT,
            alert_status VARCHAR(20) NOT NULL DEFAULT 'ok',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS source_job_notifications (
            id BIGSERIAL PRIMARY KEY,
            source_key VARCHAR(50) NOT NULL,
            event_type VARCHAR(20) NOT NULL,
            severity VARCHAR(20) NOT NULL,
            detail TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            delivered_at TIMESTAMPTZ,
            delivery_error TEXT
        )
    """))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_source_job_notifications_created
        ON source_job_notifications (created_at DESC)
    """))
    session.execute(text("""
        ALTER TABLE source_job_state
        ADD COLUMN IF NOT EXISTS source_cursor TEXT,
        ADD COLUMN IF NOT EXISTS source_data_at TIMESTAMPTZ,
        ADD COLUMN IF NOT EXISTS duration_seconds DOUBLE PRECISION,
        ADD COLUMN IF NOT EXISTS counts JSONB NOT NULL DEFAULT '{}'::jsonb
    """))


COMMON_COUNT_KEYS = (
    "records_seen",
    "records_processed",
    "records_created",
    "records_updated",
    "documents_created",
    "chunks_created",
    "relationships_processed",
)


def _source_counts(source_key: str, result: Mapping[str, Any]) -> dict[str, int | None]:
    """Map heterogeneous worker counters into one stable source payload."""
    counts: dict[str, int | None] = {key: None for key in COMMON_COUNT_KEYS}
    if source_key.startswith("edgar_"):
        counts.update({
            "records_seen": result.get("filings_seen"),
            "records_processed": result.get("filings_fetched"),
            "records_created": result.get("filings_fetched"),
            "documents_created": result.get("documents_created"),
            "chunks_created": result.get("chunks_created"),
        })
    elif source_key == "cortellis":
        counts.update({
            "records_seen": result.get("records_processed"),
            "records_processed": result.get("records_processed"),
            "records_created": result.get("records_created"),
            "records_updated": result.get("records_updated"),
            "documents_created": result.get("contracts_downloaded"),
        })
    elif source_key == "cortellis_catalog":
        counts.update({
            "records_seen": result.get("remote_unique_total"),
            "records_processed": result.get("reconciled"),
            "records_created": result.get("reconciled"),
            "documents_created": result.get("contracts_downloaded"),
        })
    elif source_key == "cortellis_contracts":
        counts.update({
            "records_seen": result.get("eligible_deals"),
            "records_processed": result.get("processed"),
            "records_updated": result.get("completed"),
            "documents_created": result.get("contracts_observed"),
        })
    elif source_key == "cortellis_deal_api":
        counts.update({
            "records_seen": result.get("eligible_deals"),
            "records_processed": result.get("processed"),
            "records_updated": result.get("completed"),
            "documents_created": result.get("sources_observed"),
        })
    elif source_key.startswith("clinicaltrials_"):
        counts.update({
            "records_seen": result.get("studies_seen"),
            "records_processed": result.get("studies_seen"),
            "records_created": result.get("studies_created"),
            "records_updated": result.get("studies_updated"),
            "relationships_processed": result.get("relationships_created"),
        })
    elif source_key == "chembl":
        counts.update({
            "records_seen": result.get("processed"),
            "records_processed": result.get("processed"),
            "records_created": result.get("identifiers_created"),
        })
    elif source_key == "open_targets":
        counts.update({
            "records_seen": result.get("processed"),
            "records_processed": result.get("processed"),
            "records_created": result.get("matched"),
            "relationships_processed": result.get("relationships_created"),
        })
    elif source_key == "uniprot":
        counts.update({
            "records_seen": result.get("processed"),
            "records_processed": result.get("processed"),
            "records_created": result.get("matched"),
        })
    elif source_key == "europe_pmc":
        counts.update({
            "records_seen": result.get("processed"),
            "records_processed": result.get("processed"),
            "records_created": result.get("publications_upserted"),
            "relationships_processed": result.get("relationships_created"),
        })
    elif source_key == "neo4j":
        companies = int(result.get("cortellis_companies") or 0) + int(
            result.get("edgar_companies") or 0
        )
        deals = int(result.get("cortellis_deals") or 0)
        relationships = int(result.get("deal_relationships") or 0)
        counts.update({
            "records_seen": companies + deals,
            "records_processed": companies + deals,
            "records_updated": companies + deals,
            "relationships_processed": relationships,
        })
    return counts


def _source_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def source_job_payload(row: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Return the versioned common operational payload for any source job."""
    now = now or datetime.now(timezone.utc)
    payload = dict(row)
    source_data_at = _source_timestamp(payload.get("source_data_at"))
    payload["payload_version"] = 1
    payload["cursor"] = payload.pop("source_cursor", None)
    payload["source_data_at"] = source_data_at
    payload["source_lag_seconds"] = (
        max(0.0, (now - source_data_at).total_seconds()) if source_data_at else None
    )
    payload["counts"] = payload.get("counts") or {
        key: None for key in COMMON_COUNT_KEYS
    }
    return payload


def _normalized_result_status(status: str | None) -> str:
    value = (status or "failed").lower()
    if value in {"completed", "complete", "success", "succeeded", "healthy"}:
        return "completed"
    if value in {"partial", "warning"}:
        return "partial"
    if value == "skipped":
        return "skipped"
    return "failed"


def retry_delay(retry_count: int) -> timedelta:
    """Exponential retry advisory, capped so operators are never left for days."""
    minutes = min(360, 15 * (2 ** max(0, retry_count - 1)))
    return timedelta(minutes=minutes)


def record_source_job_started(source_key: str) -> None:
    policy = SOURCE_POLICIES[source_key]
    try:
        with get_cortellis_session() as session:
            session.execute(text("""
                INSERT INTO source_job_state (
                    source_key, label, status, last_started_at, updated_at
                ) VALUES (
                    :source_key, :label, 'running', NOW(), NOW()
                )
                ON CONFLICT (source_key) DO UPDATE SET
                    label = EXCLUDED.label,
                    status = 'running',
                    last_started_at = NOW(),
                    updated_at = NOW()
            """), {"source_key": source_key, "label": policy.label})
            session.commit()
    except Exception as exc:  # Monitoring must never prevent the source job.
        logger.warning("Could not record source job start", source=source_key, error=str(exc))


def record_source_job_finished(source_key: str, result: Mapping[str, Any]) -> None:
    policy = SOURCE_POLICIES[source_key]
    status = _normalized_result_status(str(result.get("status", "failed")))
    error = result.get("error") or result.get("reason")
    try:
        with get_cortellis_session() as session:
            existing = session.execute(text("""
                SELECT retry_count, consecutive_failures, last_started_at
                FROM source_job_state
                WHERE source_key = :source_key
            """), {"source_key": source_key}).mappings().first() or {}
            failed = status in {"failed", "partial"}
            retry_count = int(existing.get("retry_count") or 0) + 1 if failed else 0
            consecutive = (
                int(existing.get("consecutive_failures") or 0) + 1 if failed else 0
            )
            next_retry = datetime.now(timezone.utc) + retry_delay(retry_count) if failed else None
            completed_at = datetime.now(timezone.utc)
            started_at = _source_timestamp(existing.get("last_started_at"))
            duration_seconds = (
                max(0.0, (completed_at - started_at).total_seconds())
                if started_at else None
            )
            source_cursor = result.get("cursor") or result.get("cursor_end")
            source_data_at = _source_timestamp(
                result.get("source_data_at") or result.get("target_date")
            )
            counts = _source_counts(source_key, result)
            session.execute(text("""
                INSERT INTO source_job_state (
                    source_key, label, status, last_started_at, last_completed_at,
                    last_success_at, consecutive_failures, retry_count,
                    next_retry_at, last_error, source_cursor, source_data_at,
                    duration_seconds, counts, updated_at
                ) VALUES (
                    :source_key, :label, :status, NOW(), :completed_at,
                    CASE WHEN :status = 'completed' THEN :completed_at END,
                    :consecutive_failures, :retry_count, :next_retry_at,
                    :last_error, :source_cursor, :source_data_at,
                    :duration_seconds, CAST(:counts AS JSONB), NOW()
                )
                ON CONFLICT (source_key) DO UPDATE SET
                    label = EXCLUDED.label,
                    status = EXCLUDED.status,
                    last_completed_at = EXCLUDED.last_completed_at,
                    last_success_at = CASE
                        WHEN EXCLUDED.status = 'completed' THEN EXCLUDED.last_completed_at
                        ELSE source_job_state.last_success_at
                    END,
                    consecutive_failures = EXCLUDED.consecutive_failures,
                    retry_count = EXCLUDED.retry_count,
                    next_retry_at = EXCLUDED.next_retry_at,
                    last_error = EXCLUDED.last_error,
                    source_cursor = EXCLUDED.source_cursor,
                    source_data_at = EXCLUDED.source_data_at,
                    duration_seconds = EXCLUDED.duration_seconds,
                    counts = EXCLUDED.counts,
                    updated_at = NOW()
            """), {
                "source_key": source_key,
                "label": policy.label,
                "status": status,
                "consecutive_failures": consecutive,
                "retry_count": retry_count,
                "next_retry_at": next_retry,
                "last_error": str(error)[:4000] if error else None,
                "completed_at": completed_at,
                "source_cursor": str(source_cursor) if source_cursor is not None else None,
                "source_data_at": source_data_at,
                "duration_seconds": duration_seconds,
                "counts": json.dumps(counts),
            })
            session.commit()
    except Exception as exc:
        logger.warning("Could not record source job result", source=source_key, error=str(exc))


def classify_source_job(
    row: Mapping[str, Any],
    policy: SourcePolicy,
    *,
    now: datetime | None = None,
) -> tuple[str, str]:
    """Return severity and an operator-readable reason for a source state row."""
    now = now or datetime.now(timezone.utc)
    status = str(row.get("status") or "unknown").lower()
    last_success = row.get("last_success_at")
    if isinstance(last_success, str):
        last_success = datetime.fromisoformat(last_success.replace("Z", "+00:00"))
    if last_success is not None and last_success.tzinfo is None:
        last_success = last_success.replace(tzinfo=timezone.utc)

    if status == "failed":
        return "critical", f"last run failed: {row.get('last_error') or 'unknown error'}"
    if status == "partial":
        return "warning", f"last run was partial: {row.get('last_error') or 'incomplete result'}"
    if last_success is None:
        if status == "running":
            return "ok", "first observed run is in progress"
        return "critical", "no successful run has been recorded"

    age_hours = (now - last_success).total_seconds() / 3600
    if age_hours >= policy.critical_hours:
        return "critical", f"last successful run was {age_hours:.1f}h ago"
    if age_hours >= policy.warn_hours:
        return "warning", f"last successful run was {age_hours:.1f}h ago"
    return "ok", f"last successful run was {age_hours:.1f}h ago"


def notification_transition(previous: str | None, current: str) -> str | None:
    """Map state changes to one alert/recovery event, suppressing duplicates."""
    previous = previous or "ok"
    if current in {"warning", "critical"} and current != previous:
        return "alert"
    if current == "ok" and previous in {"warning", "critical"}:
        return "recovery"
    return None


def _deliver_notification(payload: Mapping[str, Any]) -> tuple[bool, str | None]:
    delivered = False
    errors: list[str] = []
    if settings.source_health_webhook_url:
        try:
            request = Request(
                settings.source_health_webhook_url,
                data=json.dumps(dict(payload)).encode(),
                headers={"Content-Type": "application/json", "User-Agent": "OneBD-Source-Monitor/1.0"},
                method="POST",
            )
            with urlopen(request, timeout=10) as response:
                delivered = 200 <= response.status < 300
        except Exception as exc:
            errors.append(f"webhook: {exc}")

    if settings.source_health_alert_email:
        try:
            from unified_api.services.email_digest import send_digest_email

            subject = f"OneBD source {payload['event_type']}: {payload['label']}"
            html = (
                f"<h2>{subject}</h2><p>Severity: {payload['severity']}</p>"
                f"<p>{payload['detail']}</p><p>{payload['observed_at']}</p>"
            )
            delivered = send_digest_email(
                settings.source_health_alert_email, subject, html
            ) or delivered
        except Exception as exc:
            errors.append(f"email: {exc}")

    if not settings.source_health_webhook_url and not settings.source_health_alert_email:
        errors.append("no delivery channel configured")
    return delivered, "; ".join(errors) or None


def _bootstrap_legacy_source_states(session) -> None:
    """Seed the common table from trustworthy pre-existing sync history."""
    existing = {
        row[0] for row in session.execute(text(
            "SELECT source_key FROM source_job_state"
        )).all()
    }
    if "cortellis" not in existing and session.execute(text(
        "SELECT to_regclass('public.sync_log')"
    )).scalar():
        latest = session.execute(text("""
            SELECT status, started_at, completed_at, error_message
            FROM sync_log ORDER BY started_at DESC LIMIT 1
        """)).mappings().first()
        if latest:
            last_success = session.execute(text("""
                SELECT MAX(completed_at) FROM sync_log WHERE status = 'completed'
            """)).scalar()
            session.execute(text("""
                INSERT INTO source_job_state (
                    source_key, label, status, last_started_at,
                    last_completed_at, last_success_at, last_error, updated_at
                ) VALUES (
                    'cortellis', :label, :status, :started_at,
                    :completed_at, :last_success_at, :last_error, NOW()
                ) ON CONFLICT (source_key) DO NOTHING
            """), {
                "label": SOURCE_POLICIES["cortellis"].label,
                "status": _normalized_result_status(latest["status"]),
                "started_at": latest["started_at"],
                "completed_at": latest["completed_at"],
                "last_success_at": last_success,
                "last_error": latest["error_message"],
            })

    missing_edgar = {"edgar_recent", "edgar_backfill"} - existing
    if not missing_edgar:
        return
    try:
        from unified_api.services.database import get_edgar_source_session

        with get_edgar_source_session() as edgar:
            has_runs = bool(edgar.execute(text(
                "SELECT to_regclass('public.edgar_sync_runs')"
            )).scalar())
            for source_key, table_name, lane in (
                ("edgar_recent", "edgar_recent_sync_state", "recent"),
                ("edgar_backfill", "edgar_sync_state", "backfill"),
            ):
                if source_key not in missing_edgar:
                    continue
                if not edgar.execute(text(
                    "SELECT to_regclass(:table_name)"
                ), {"table_name": f"public.{table_name}"}).scalar():
                    continue
                state = edgar.execute(text(
                    f"SELECT * FROM {table_name} WHERE id = 1"
                )).mappings().first()
                if not state:
                    continue
                last_success = None
                if has_runs:
                    last_success = edgar.execute(text("""
                        SELECT MAX(completed_at)
                        FROM edgar_sync_runs
                        WHERE lane = :lane AND status = 'completed'
                    """), {"lane": lane}).scalar()
                if last_success is None and state.get("status") == "completed":
                    last_success = state.get("completed_at") or state.get("last_run_at")
                session.execute(text("""
                    INSERT INTO source_job_state (
                        source_key, label, status, last_started_at,
                        last_completed_at, last_success_at, last_error, updated_at
                    ) VALUES (
                        :source_key, :label, :status, :started_at,
                        :completed_at, :last_success_at, :last_error, NOW()
                    ) ON CONFLICT (source_key) DO NOTHING
                """), {
                    "source_key": source_key,
                    "label": SOURCE_POLICIES[source_key].label,
                    "status": _normalized_result_status(state.get("status")),
                    "started_at": state.get("started_at") or state.get("last_run_at"),
                    "completed_at": state.get("completed_at"),
                    "last_success_at": last_success,
                    "last_error": state.get("last_error") or state.get("error_message"),
                })
    except Exception as exc:
        logger.warning("Could not bootstrap EDGAR monitoring state", error=str(exc))


def monitor_source_jobs() -> dict[str, Any]:
    """Classify source jobs and persist/deliver only state transitions."""
    now = datetime.now(timezone.utc)
    pending: list[dict[str, Any]] = []
    states: list[dict[str, Any]] = []
    with get_cortellis_session() as session:
        _bootstrap_legacy_source_states(session)
        rows = session.execute(text("""
            SELECT * FROM source_job_state ORDER BY source_key
        """)).mappings().all()
        for raw in rows:
            row = dict(raw)
            policy = SOURCE_POLICIES.get(row["source_key"])
            if policy is None:
                continue
            severity, detail = classify_source_job(row, policy, now=now)
            event_type = notification_transition(row.get("alert_status"), severity)
            states.append({"source": row["source_key"], "severity": severity, "detail": detail})
            if event_type:
                event_detail = detail if event_type == "alert" else f"Recovered: {detail}"
                event_id = session.execute(text("""
                    INSERT INTO source_job_notifications (
                        source_key, event_type, severity, detail
                    ) VALUES (:source_key, :event_type, :severity, :detail)
                    RETURNING id
                """), {
                    "source_key": row["source_key"],
                    "event_type": event_type,
                    "severity": severity,
                    "detail": event_detail,
                }).scalar_one()
                session.execute(text("""
                    UPDATE source_job_state
                    SET alert_status = :severity, updated_at = NOW()
                    WHERE source_key = :source_key
                """), {"severity": severity, "source_key": row["source_key"]})
                pending.append({
                    "id": event_id,
                    "source": row["source_key"],
                    "label": policy.label,
                    "event_type": event_type,
                    "severity": severity,
                    "detail": event_detail,
                    "observed_at": now.isoformat(),
                })
        session.commit()

    for payload in pending:
        delivered, delivery_error = _deliver_notification(payload)
        with get_cortellis_session() as session:
            session.execute(text("""
                UPDATE source_job_notifications
                SET delivered_at = CASE WHEN :delivered THEN NOW() END,
                    delivery_error = :delivery_error
                WHERE id = :id
            """), {
                "delivered": delivered,
                "delivery_error": delivery_error,
                "id": payload["id"],
            })
            session.commit()
        log = logger.info if delivered else logger.warning
        log("Source health notification", **payload, delivery_error=delivery_error)

    return {"status": "completed", "sources": states, "notifications": len(pending)}


def read_source_job_states(session) -> list[dict[str, Any]]:
    return [source_job_payload(row) for row in session.execute(text("""
        SELECT source_key, label, status, last_started_at, last_completed_at,
               last_success_at, consecutive_failures, retry_count,
               next_retry_at, last_error, alert_status, source_cursor,
               source_data_at, duration_seconds, counts, updated_at
        FROM source_job_state
        ORDER BY source_key
    """)).mappings().all()]
