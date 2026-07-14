"""Exact Cortellis-to-ClinicalTrials citations and evidence timelines."""

from __future__ import annotations

from datetime import date, datetime
from html import unescape
import re
from typing import Any, Mapping, Sequence

from sqlalchemy import text


DEAL_TRIAL_LINK_PARSER_VERSION = 1
DEAL_TRIAL_LINK_METHOD = "exact_nct_citation"
_NCT_ID = re.compile(
    r"(?<![A-Z0-9])NCT(?P<number>\d{8})(?![A-Z0-9])",
    re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")


def _clean_excerpt(value: str) -> str:
    return _SPACE.sub(" ", _TAG.sub(" ", unescape(value))).strip()


def extract_nct_citations(
    source_text: str | None,
    *,
    context_chars: int = 240,
) -> list[dict[str, Any]]:
    """Return only explicit NCT######## citations with replayable offsets."""
    if not source_text:
        return []
    context_chars = max(40, min(1000, int(context_chars)))
    citations = []
    for match in _NCT_ID.finditer(source_text):
        start, end = match.span()
        excerpt_start = max(0, start - context_chars)
        excerpt_end = min(len(source_text), end + context_chars)
        citations.append({
            "nct_id": f"NCT{match.group('number')}",
            "source_char_start": start,
            "source_char_end": end,
            "source_excerpt": _clean_excerpt(
                source_text[excerpt_start:excerpt_end]
            ),
        })
    return citations


def ensure_deal_trial_link_schema(session) -> None:
    """Create the versioned exact-citation link and scan-state tables."""
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS deal_clinical_trial_links (
            id BIGSERIAL PRIMARY KEY,
            deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
            nct_id VARCHAR(11) NOT NULL,
            link_method VARCHAR(50) NOT NULL,
            source_type VARCHAR(100) NOT NULL,
            source_record_id BIGINT NOT NULL,
            source_sha256 CHAR(64) NOT NULL,
            source_char_start INTEGER NOT NULL,
            source_char_end INTEGER NOT NULL,
            source_excerpt TEXT NOT NULL,
            parser_version INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (
                deal_id, nct_id, source_type, source_record_id,
                source_char_start, parser_version
            )
        )
    """))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_deal_clinical_trial_links_deal
        ON deal_clinical_trial_links (deal_id, nct_id)
    """))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_deal_clinical_trial_links_nct
        ON deal_clinical_trial_links (nct_id, deal_id)
    """))
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS deal_clinical_trial_link_state (
            deal_id INTEGER PRIMARY KEY REFERENCES deals(id) ON DELETE CASCADE,
            source_record_id BIGINT NOT NULL,
            source_sha256 CHAR(64) NOT NULL,
            parser_version INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL,
            citations_found INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))


def extract_deal_trial_link_batch(
    session,
    *,
    batch_size: int = 1000,
) -> dict[str, Any]:
    """Scan current lossless Cortellis payloads for exact NCT citations."""
    batch_size = max(1, min(5000, int(batch_size)))
    locked = session.execute(text(
        "SELECT pg_try_advisory_xact_lock("
        "hashtext('onebd_deal_clinical_trial_links'))"
    )).scalar()
    if not locked:
        return {
            "status": "busy",
            "processed": 0,
            "citation_mentions": 0,
            "cited_trials": 0,
            "errors": 0,
            "parser_version": DEAL_TRIAL_LINK_PARSER_VERSION,
        }

    ensure_deal_trial_link_schema(session)
    rows = session.execute(text("""
        WITH current AS (
            SELECT DISTINCT ON (history.deal_id)
                   history.id, history.deal_id, history.response_sha256,
                   history.response_body
            FROM cortellis_expanded_response_history history
            ORDER BY history.deal_id, history.last_fetched_at DESC, history.id DESC
        )
        SELECT current.id AS source_record_id, current.deal_id,
               current.response_sha256, current.response_body
        FROM current
        LEFT JOIN deal_clinical_trial_link_state state
          ON state.deal_id = current.deal_id
        WHERE state.deal_id IS NULL
           OR state.source_record_id <> current.id
           OR state.source_sha256 <> current.response_sha256
           OR state.parser_version <> :parser_version
           OR state.status = 'failed'
        ORDER BY current.deal_id
        LIMIT :batch_size
    """), {
        "parser_version": DEAL_TRIAL_LINK_PARSER_VERSION,
        "batch_size": batch_size,
    }).mappings().all()

    processed = 0
    citation_mentions = 0
    cited_trials: set[str] = set()
    errors = 0
    for row in rows:
        try:
            with session.begin_nested():
                citations = extract_nct_citations(row["response_body"])
                session.execute(text("""
                    DELETE FROM deal_clinical_trial_links
                    WHERE deal_id = :deal_id AND link_method = :link_method
                """), {
                    "deal_id": row["deal_id"],
                    "link_method": DEAL_TRIAL_LINK_METHOD,
                })
                for citation in citations:
                    session.execute(text("""
                        INSERT INTO deal_clinical_trial_links (
                            deal_id, nct_id, link_method, source_type,
                            source_record_id, source_sha256,
                            source_char_start, source_char_end, source_excerpt,
                            parser_version
                        ) VALUES (
                            :deal_id, :nct_id, :link_method, :source_type,
                            :source_record_id, :source_sha256,
                            :source_char_start, :source_char_end, :source_excerpt,
                            :parser_version
                        )
                        ON CONFLICT DO NOTHING
                    """), {
                        **citation,
                        "deal_id": row["deal_id"],
                        "link_method": DEAL_TRIAL_LINK_METHOD,
                        "source_type": "cortellis_expanded_deal_api",
                        "source_record_id": row["source_record_id"],
                        "source_sha256": row["response_sha256"],
                        "parser_version": DEAL_TRIAL_LINK_PARSER_VERSION,
                    })
                session.execute(text("""
                    INSERT INTO deal_clinical_trial_link_state (
                        deal_id, source_record_id, source_sha256,
                        parser_version, status, citations_found,
                        last_error, processed_at
                    ) VALUES (
                        :deal_id, :source_record_id, :source_sha256,
                        :parser_version, 'completed', :citations_found,
                        NULL, NOW()
                    )
                    ON CONFLICT (deal_id) DO UPDATE SET
                        source_record_id = EXCLUDED.source_record_id,
                        source_sha256 = EXCLUDED.source_sha256,
                        parser_version = EXCLUDED.parser_version,
                        status = 'completed',
                        citations_found = EXCLUDED.citations_found,
                        last_error = NULL,
                        processed_at = NOW()
                """), {
                    "deal_id": row["deal_id"],
                    "source_record_id": row["source_record_id"],
                    "source_sha256": row["response_sha256"],
                    "parser_version": DEAL_TRIAL_LINK_PARSER_VERSION,
                    "citations_found": len(citations),
                })
                processed += 1
                citation_mentions += len(citations)
                cited_trials.update(item["nct_id"] for item in citations)
        except Exception as exc:
            errors += 1
            session.execute(text("""
                INSERT INTO deal_clinical_trial_link_state (
                    deal_id, source_record_id, source_sha256,
                    parser_version, status, citations_found,
                    last_error, processed_at
                ) VALUES (
                    :deal_id, :source_record_id, :source_sha256,
                    :parser_version, 'failed', 0, :last_error, NOW()
                )
                ON CONFLICT (deal_id) DO UPDATE SET
                    source_record_id = EXCLUDED.source_record_id,
                    source_sha256 = EXCLUDED.source_sha256,
                    parser_version = EXCLUDED.parser_version,
                    status = 'failed', citations_found = 0,
                    last_error = EXCLUDED.last_error,
                    processed_at = NOW()
            """), {
                "deal_id": row["deal_id"],
                "source_record_id": row["source_record_id"],
                "source_sha256": row["response_sha256"],
                "parser_version": DEAL_TRIAL_LINK_PARSER_VERSION,
                "last_error": str(exc)[:2000],
            })

    return {
        "status": "completed",
        "processed": processed,
        "citation_mentions": citation_mentions,
        "cited_trials": len(cited_trials),
        "errors": errors,
        "parser_version": DEAL_TRIAL_LINK_PARSER_VERSION,
    }


def deal_trial_link_status(session) -> dict[str, Any]:
    """Return current-payload scan coverage and registry match quality."""
    ensure_deal_trial_link_schema(session)
    row = session.execute(text("""
        WITH current AS (
            SELECT DISTINCT ON (history.deal_id)
                   history.id, history.deal_id, history.response_sha256
            FROM cortellis_expanded_response_history history
            ORDER BY history.deal_id, history.last_fetched_at DESC, history.id DESC
        )
        SELECT
          (SELECT COUNT(*) FROM current) AS eligible_deals,
          (SELECT COUNT(*) FROM current
           JOIN deal_clinical_trial_link_state state USING (deal_id)
           WHERE state.source_record_id = current.id
             AND state.source_sha256 = current.response_sha256
             AND state.parser_version = :parser_version
             AND state.status = 'completed') AS deals_scanned,
          (SELECT COUNT(*) FROM deal_clinical_trial_link_state
           WHERE parser_version = :parser_version AND status = 'failed') AS failed_deals,
          (SELECT COUNT(*) FROM deal_clinical_trial_links
           WHERE parser_version = :parser_version) AS citation_mentions,
          (SELECT COUNT(DISTINCT deal_id) FROM deal_clinical_trial_links
           WHERE parser_version = :parser_version) AS deals_with_citations,
          (SELECT COUNT(DISTINCT nct_id) FROM deal_clinical_trial_links
           WHERE parser_version = :parser_version) AS cited_nct_ids,
          (SELECT COUNT(DISTINCT link.nct_id)
           FROM deal_clinical_trial_links link
           JOIN clinical_trials trial ON trial.nct_id = link.nct_id
           WHERE link.parser_version = :parser_version) AS registry_matched_nct_ids
    """), {"parser_version": DEAL_TRIAL_LINK_PARSER_VERSION}).mappings().one()
    result = dict(row)
    eligible = int(result["eligible_deals"] or 0)
    result["scan_coverage_pct"] = (
        round(100 * int(result["deals_scanned"] or 0) / eligible, 2)
        if eligible else 0.0
    )
    result["unmatched_nct_ids"] = max(
        0,
        int(result["cited_nct_ids"] or 0)
        - int(result["registry_matched_nct_ids"] or 0),
    )
    result["parser_version"] = DEAL_TRIAL_LINK_PARSER_VERSION
    result["link_method"] = DEAL_TRIAL_LINK_METHOD
    return result


def deal_trial_link_validation_status(session) -> dict[str, Any]:
    """Validate every exact citation against its archived source response."""
    status = deal_trial_link_status(session)
    row = session.execute(text("""
        SELECT
          COUNT(*) FILTER (
            WHERE link.nct_id !~ '^NCT[0-9]{8}$'
          ) AS invalid_nct_ids,
          COUNT(*) FILTER (
            WHERE link.source_char_start < 0
               OR link.source_char_end <= link.source_char_start
               OR length(link.source_sha256) <> 64
          ) AS invalid_provenance,
          COUNT(*) FILTER (
            WHERE history.id IS NULL
          ) AS missing_source_records,
          COUNT(*) FILTER (
            WHERE history.id IS NOT NULL
              AND history.response_sha256 <> link.source_sha256
          ) AS source_hash_mismatches,
          COUNT(*) FILTER (
            WHERE history.id IS NOT NULL AND UPPER(substring(
                history.response_body
                FROM link.source_char_start + 1
                FOR link.source_char_end - link.source_char_start
            )) <> link.nct_id
          ) AS source_offset_mismatches
        FROM deal_clinical_trial_links link
        LEFT JOIN cortellis_expanded_response_history history
          ON history.id = link.source_record_id
        WHERE link.parser_version = :parser_version
          AND link.link_method = :link_method
    """), {
        "parser_version": DEAL_TRIAL_LINK_PARSER_VERSION,
        "link_method": DEAL_TRIAL_LINK_METHOD,
    }).mappings().one()
    report = {**status, **dict(row)}
    cited = int(report["cited_nct_ids"] or 0)
    matched = int(report["registry_matched_nct_ids"] or 0)
    report["registry_match_pct"] = (
        round(100 * matched / cited, 2) if cited else 0.0
    )
    report["technical_release_ready"] = bool(
        report["scan_coverage_pct"] == 100.0
        and not report["failed_deals"]
        and report["citation_mentions"] > 0
        and not report["invalid_nct_ids"]
        and not report["invalid_provenance"]
        and not report["missing_source_records"]
        and not report["source_hash_mismatches"]
        and not report["source_offset_mismatches"]
    )
    return report


def _as_date_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return str(value)[:10]


def _event_category(event_type: str | None) -> str:
    normalized = (event_type or "").lower()
    if "regulatory" in normalized:
        return "regulatory"
    if "development" in normalized:
        return "development"
    return "deal"


def build_deal_evidence_timeline(
    cortellis_events: Sequence[Mapping[str, Any]],
    cited_trials: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build one source-labeled timeline without inferred trial links."""
    events: list[dict[str, Any]] = []
    for row in cortellis_events:
        event_type = _clean_excerpt(str(row.get("event_type") or "")) or None
        events.append({
            "event_date": _as_date_string(row.get("event_date")),
            "date_precision": "day" if row.get("event_date") else None,
            "category": _event_category(event_type),
            "event_type": event_type or "Deal update",
            "stage": _clean_excerpt(str(row.get("stage") or "")) or None,
            "summary": _clean_excerpt(str(row.get("summary") or "")) or None,
            "source": "cortellis_deals_api",
            "source_record_id": str(row.get("id")),
            "source_url": None,
            "nct_id": None,
            "link_method": None,
            "citation_evidence": [],
        })

    for row in cited_trials:
        nct_id = str(row["nct_id"])
        evidence = row.get("citation_evidence") or []
        common = {
            "source": "clinicaltrials.gov_api_v2",
            "source_record_id": nct_id,
            "source_url": row.get("source_url"),
            "nct_id": nct_id,
            "link_method": DEAL_TRIAL_LINK_METHOD,
            "citation_evidence": evidence,
        }
        if row.get("brief_title") is None:
            events.append({
                **common,
                "event_date": None,
                "date_precision": None,
                "category": "clinical_trial",
                "event_type": "Cited trial unavailable in registry",
                "stage": None,
                "summary": f"{nct_id} is cited in the Cortellis deal payload.",
            })
            continue
        title = row.get("brief_title") or nct_id
        phases = row.get("phases") or []
        stage = ", ".join(phases) if isinstance(phases, list) else str(phases)
        trial_dates = (
            (
                "Trial start",
                row.get("start_date"),
                row.get("start_date_raw"),
                row.get("start_date_type"),
            ),
            (
                "Primary completion",
                row.get("primary_completion_date"),
                row.get("primary_completion_date_raw"),
                row.get("primary_completion_date_type"),
            ),
            (
                "Study completion",
                row.get("completion_date"),
                row.get("completion_date_raw"),
                row.get("completion_date_type"),
            ),
        )
        for event_type, event_date, raw_date, date_type in trial_dates:
            if not event_date:
                continue
            events.append({
                **common,
                "event_date": _as_date_string(event_date),
                "date_precision": raw_date,
                "category": "clinical_trial",
                "event_type": event_type,
                "stage": stage or None,
                "summary": title,
                "date_type": date_type,
            })
        if row.get("last_update_posted"):
            events.append({
                **common,
                "event_date": _as_date_string(row.get("last_update_posted")),
                "date_precision": row.get("last_update_posted_raw"),
                "category": "clinical_status",
                "event_type": "Registry status update",
                "stage": stage or None,
                "summary": (
                    f"{title} — current status: "
                    f"{row.get('overall_status') or 'unknown'}"
                ),
            })

    events.sort(key=lambda event: (
        event.get("event_date") is not None,
        event.get("event_date") or "",
        event.get("event_type") or "",
    ), reverse=True)
    return events


def deal_evidence_timeline(session, deal_id: int) -> dict[str, Any] | None:
    """Return exact-citation trial events and explicit Cortellis milestones."""
    ensure_deal_trial_link_schema(session)
    exists = session.execute(
        text("SELECT 1 FROM deals WHERE id = :deal_id"),
        {"deal_id": deal_id},
    ).scalar()
    if not exists:
        return None
    cortellis_events = session.execute(text("""
        SELECT id, event_date, event_type, stage, summary
        FROM deal_timeline_events
        WHERE deal_id = :deal_id
        ORDER BY event_date DESC NULLS LAST, id DESC
    """), {"deal_id": deal_id}).mappings().all()
    cited_trials = session.execute(text("""
        SELECT link.nct_id,
               trial.brief_title, trial.overall_status, trial.phases,
               trial.start_date, trial.start_date_raw, trial.start_date_type,
               trial.primary_completion_date,
               trial.primary_completion_date_raw,
               trial.primary_completion_date_type,
               trial.completion_date, trial.completion_date_raw,
               trial.completion_date_type,
               trial.last_update_posted, trial.last_update_posted_raw,
               trial.source_url,
               jsonb_agg(jsonb_build_object(
                   'source_type', link.source_type,
                   'source_record_id', link.source_record_id,
                   'source_sha256', link.source_sha256,
                   'source_char_start', link.source_char_start,
                   'source_char_end', link.source_char_end,
                   'source_excerpt', link.source_excerpt
               ) ORDER BY link.source_char_start) AS citation_evidence
        FROM deal_clinical_trial_links link
        LEFT JOIN clinical_trials trial ON trial.nct_id = link.nct_id
        WHERE link.deal_id = :deal_id
          AND link.parser_version = :parser_version
          AND link.link_method = :link_method
        GROUP BY link.nct_id, trial.brief_title, trial.overall_status,
                 trial.phases, trial.start_date, trial.start_date_raw,
                 trial.start_date_type, trial.primary_completion_date,
                 trial.primary_completion_date_raw,
                 trial.primary_completion_date_type, trial.completion_date,
                 trial.completion_date_raw, trial.completion_date_type,
                 trial.last_update_posted, trial.last_update_posted_raw,
                 trial.source_url
        ORDER BY link.nct_id
    """), {
        "deal_id": deal_id,
        "parser_version": DEAL_TRIAL_LINK_PARSER_VERSION,
        "link_method": DEAL_TRIAL_LINK_METHOD,
    }).mappings().all()
    events = build_deal_evidence_timeline(cortellis_events, cited_trials)
    cited = [dict(row) for row in cited_trials]
    return {
        "deal_id": deal_id,
        "events": events,
        "summary": {
            "event_count": len(events),
            "cortellis_event_count": len(cortellis_events),
            "explicit_regulatory_event_count": sum(
                event["category"] == "regulatory" for event in events
            ),
            "exact_cited_trial_count": len(cited),
            "matched_registry_trial_count": sum(
                row.get("brief_title") is not None for row in cited_trials
            ),
            "link_method": DEAL_TRIAL_LINK_METHOD,
            "parser_version": DEAL_TRIAL_LINK_PARSER_VERSION,
        },
        "cited_trials": cited,
        "provenance_note": (
            "Clinical trials are included only when an exact NCT######## identifier "
            "appears in the lossless Cortellis deal payload. Shared drug or disease "
            "names are not treated as deal-specific links."
        ),
    }
